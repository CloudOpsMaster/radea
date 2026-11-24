"""Terraform source review: rules, parser robustness and the safe variants."""

import json
import textwrap

import pytest
from click.testing import CliRunner

from radea.cli import main
from radea.static_review.catalog import CATALOG
from radea.static_review.runner import run_terraform
from radea.static_review.tf import parse

LIMIT = 8 * 1024 * 1024


def review(tmp_path, text, name="main.tf"):
    path = tmp_path / name
    path.write_text(textwrap.dedent(text))
    return run_terraform([str(path)], LIMIT)


def rules_in(report):
    return {f["rule"] for f in report["findings"]}


def sg(cidr='"0.0.0.0/0"', frm=22, to=22, proto="tcp", extra=""):
    return f"""
    resource "aws_security_group_rule" "r" {{
      type        = "ingress"
      from_port   = {frm}
      to_port     = {to}
      protocol    = "{proto}"
      cidr_blocks = [{cidr}]
      {extra}
    }}
    """


CASES = {
    "TF001": sg(),
    "TF002": sg(frm=443, to=443),
    "TF003": 'resource "aws_db_instance" "d" {\n  password = "hunter2hunter2"\n}\n',
    "TF004": 'resource "aws_ebs_volume" "v" {\n  encrypted = false\n}\n',
    "TF005": 'resource "aws_s3_bucket" "b" {\n  acl = "public-read"\n}\n',
    "TF006": (
        'terraform {\n  required_providers {\n    aws = { source = "hashicorp/aws" }\n  }\n}\n'
    ),
    "TF007": 'resource "aws_db_instance" "d" {\n  skip_final_snapshot = true\n}\n',
    "TF008": 'resource "aws_s3_bucket" "b" {\n  bucket = "x"\n}\n',
}

CLEAN = """
terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}
resource "aws_s3_bucket" "b" {
  bucket = "x"
  lifecycle { prevent_destroy = true }
}
"""


def test_clean_source_is_quiet(tmp_path):
    assert review(tmp_path, CLEAN)["findings"] == []


@pytest.mark.parametrize("rule", sorted(CASES))
def test_rule_fires(tmp_path, rule):
    assert rule in rules_in(review(tmp_path, CASES[rule])), rule


def test_every_terraform_rule_has_a_case():
    assert set(CASES) == {k for k in CATALOG if k.startswith("TF")}


@pytest.mark.parametrize(
    ("snippet", "expected"),
    [
        (sg(frm=3306, to=3306), "TF001"),
        (sg(frm=0, to=65535), "TF001"),
        (sg(frm=0, to=0, proto="-1"), "TF001"),
        (sg(frm=20, to=25), "TF001"),  # range containing 22
        (sg(cidr='"::/0"', frm=80, to=80), "TF002"),
        (sg(cidr='"10.0.0.0/8"'), None),
        (sg(cidr="var.admin_cidr"), None),
    ],
)
def test_ingress_port_logic(tmp_path, snippet, expected):
    found = rules_in(review(tmp_path, snippet)) & {"TF001", "TF002"}
    assert found == ({expected} if expected else set())


def test_inline_ingress_blocks_and_other_clouds(tmp_path):
    text = """
    resource "aws_security_group" "g" {
      ingress {
        from_port   = 5432
        to_port     = 5432
        protocol    = "tcp"
        cidr_blocks = ["0.0.0.0/0"]
      }
    }
    resource "google_compute_firewall" "f" {
      source_ranges = ["0.0.0.0/0"]
      allow {
        protocol = "tcp"
        ports    = ["3389"]
      }
    }
    resource "azurerm_network_security_rule" "a" {
      direction              = "Inbound"
      access                 = "Allow"
      source_address_prefix  = "*"
      destination_port_range = "22"
    }
    """
    targets = {f["target"] for f in review(tmp_path, text)["findings"] if f["rule"] == "TF001"}
    assert targets == {
        "aws_security_group.g",
        "google_compute_firewall.f",
        "azurerm_network_security_rule.a",
    }


@pytest.mark.parametrize(
    "text",
    [
        'resource "aws_db_instance" "d" {\n  password = var.db_password\n}\n',
        'resource "aws_db_instance" "d" {\n  password = data.aws_secret.x.secret_string\n}\n',
        'resource "aws_x" "d" {\n  secret_name = "my-secret"\n  token_ttl_enabled = true\n}\n',
        'variable "region" {\n  default = "eu-west-1"\n}\n',
        'module "m" {\n  source = "./modules/m"\n}\n',
        'module "m" {\n  source  = "x/y/z"\n  version = "~> 1.2"\n}\n',
        'module "m" {\n  source = "git::https://example.org/m.git?ref=v1.2.3"\n}\n',
        'terraform {\n  required_providers {\n    aws = "~> 5.0"\n  }\n}\n',
        'resource "aws_db_instance" "d" {\n  # password = "commented-out"\n}\n',
        'resource "aws_db_instance" "d" {\n  tags = { Note = "password = \\"x\\"" }\n}\n',
    ],
)
def test_safe_patterns_are_not_flagged(tmp_path, text):
    assert rules_in(review(tmp_path, text)) <= {"TF008"}, review(tmp_path, text)["findings"]


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ('module "m" {\n  source = "x/y/z"\n}\n', "TF006"),
        ('module "m" {\n  source  = "x/y/z"\n  version = ">= 1.0"\n}\n', "TF006"),
        ('module "m" {\n  source = "git::https://e.org/m.git?ref=main"\n}\n', "TF006"),
        ('module "m" {\n  source = "git::https://e.org/m.git"\n}\n', "TF006"),
        ('terraform {\n  required_providers {\n    aws = ">= 4.0"\n  }\n}\n', "TF006"),
        ('variable "db_password" {\n  default = "hunter2hunter2"\n}\n', "TF003"),
        (
            'resource "aws_s3_bucket_public_access_block" "p" {\n  block_public_acls = false\n}\n',
            "TF005",
        ),
        ('resource "aws_db_instance" "d" {\n  deletion_protection = false\n}\n', "TF007"),
    ],
)
def test_more_rule_variants(tmp_path, text, rule):
    assert rule in rules_in(review(tmp_path, text))


def test_parser_handles_heredocs_comments_and_nested_expressions():
    blocks = parse(
        textwrap.dedent(
            """
            /* block comment { with braces */
            resource "aws_iam_policy" "p" {   # trailing comment
              policy = <<-EOT
                { "Statement": [ { "Action": "*" } ] }
              EOT
              name   = "x}"
              list   = [
                "a",
                "b",
              ]
              json   = jsonencode({ a = { b = [1, 2] } })
              inner {
                key = "${var.x}"
              }
            }
            resource "aws_s3_bucket" "after" {}
            """
        )
    )
    assert [b.labels for b in blocks] == [["aws_iam_policy", "p"], ["aws_s3_bucket", "after"]]
    first = blocks[0]
    assert first.literal("name") == "x}"
    assert first.strings("list") == ["a", "b"]
    assert first.children[0].kind == "inner"


def test_line_numbers_and_secret_values_not_printed(tmp_path):
    text = 'resource "aws_db_instance" "d" {\n  engine = "x"\n  password = "hunter2hunter2"\n}\n'
    report = review(tmp_path, text)
    finding = next(f for f in report["findings"] if f["rule"] == "TF003")
    assert finding["line"] == 3
    assert "hunter2" not in json.dumps(report)


def test_malformed_input_does_not_crash_or_hang(tmp_path):
    garbage = 'resource "a" "b" {\n  x = "unterminated\n  y = [1, 2\n}}}} {{{ \n' * 50
    assert review(tmp_path, garbage)["summary"]["files"] == 1


def test_examples_and_cli(tmp_path):
    assert run_terraform(["examples/terraform/hardened.tf"], LIMIT)["findings"] == []
    insecure = run_terraform(["examples/terraform/insecure.tf"], LIMIT)
    assert {"TF001", "TF003", "TF004", "TF005", "TF006", "TF007", "TF008"} <= rules_in(insecure)
    runner = CliRunner()
    assert runner.invoke(main, ["tf-review", "examples/terraform/hardened.tf"]).exit_code == 0
    assert runner.invoke(main, ["tf-review", "examples/terraform/insecure.tf"]).exit_code == 2
    assert runner.invoke(main, ["tf-review", str(tmp_path)]).exit_code == 1
