#!/usr/bin/env bash
# Static verification by default. With --minikube, own an isolated cluster for the test.
set -euo pipefail
umask 077

usage() {
    echo "Usage: $0 [--minikube|--admission|--canary|--gitops|--preview|--preview-ttl|--gateway|--source-to-pod|--operator|--telemetry]" >&2
}
[[ $# -le 1 ]] || { usage; exit 1; }
mode=${1:-}
case $mode in
    ""|--minikube|--admission|--canary|--gitops|--preview|--preview-ttl|--gateway|--source-to-pod|--operator|--telemetry) ;;
    *) usage; exit 1 ;;
esac

root=$(cd "$(dirname "$0")/.." && pwd)
chart="$root/examples/k8s-lab"
# QEMU's macOS monitor socket needs a short absolute path.
work=$(mktemp -d /tmp/radea-lab.XXXXXXXX)
profile=$(basename "$work" | tr '[:upper:].' '[:lower:]-')
cluster_started=false
export KUBECONFIG="$work/kubeconfig"
export MINIKUBE_HOME="$work"
printf 'apiVersion: v1\nkind: Config\n' > "$KUBECONFIG"

cleanup() {
    local status=$?
    trap - EXIT
    if $cluster_started; then
        if [[ $status != 0 ]]; then
            kubectl --context "$profile" --request-timeout=10s -n radea-lab \
                get pods,events >&2 || true
            if [[ $mode == --operator ]]; then
                kubectl --context "$profile" --request-timeout=10s -n radea-lab \
                    logs deployment/radea-message-controller --tail=20 >&2 || true
            fi
            if [[ $mode == --source-to-pod ]]; then
                kubectl --context "$profile" --request-timeout=10s -n radea-source-to-pod-pr-1 \
                    get pods,events >&2 || true
            fi
            for hook in radea-lab-test radea-preview-test; do
                kubectl --context "$profile" --request-timeout=10s -n radea-lab logs "$hook" \
                    >&2 2>/dev/null || true
            done
        fi
        if ! minikube delete --profile "$profile"; then
            echo "Minikube cleanup failed. Cluster state retained in $work" >&2
            exit 1
        fi
    fi
    rm -rf "$work"
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

helm lint "$chart"
if helm template radea-lab "$chart" --set replicaCount=0 > "$work/invalid.log" 2>&1; then
    echo "Chart schema accepted zero replicas" >&2
    exit 1
fi
if ! grep -q 'replicaCount' "$work/invalid.log"; then
    cat "$work/invalid.log" >&2
    exit 1
fi
helm template radea-lab "$chart" > "$work/before.yaml"
helm template radea-lab "$chart" --set replicaCount=3 > "$work/after.yaml"
radea k8s-review "$chart" "$work/before.yaml" "$root/examples/k8s-operator/crd.yaml"
radea manifest-diff "$work/before.yaml" "$work/after.yaml"

if command -v kubectl >/dev/null; then
    mkdir "$work/kustomize"
    cp "$work/before.yaml" "$work/kustomize/base.yaml"
    cat > "$work/kustomize/kustomization.yaml" <<'EOF'
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - base.yaml
replicas:
  - name: radea-lab
    count: 3
EOF
    kubectl kustomize "$work/kustomize" > "$work/kustomize.yaml"
    echo "Helm and Kustomize replica overrides produce equivalent manifests"
    radea manifest-diff "$work/after.yaml" "$work/kustomize.yaml" --fail-on-change
fi

if [[ -n ${1:-} ]]; then
    for dependency in minikube kubectl python3 git; do
        if ! command -v "$dependency" >/dev/null; then
            echo "Required for --minikube: $dependency" >&2
            exit 1
        fi
    done
    cluster_started=true
    minikube start --profile "$profile"
    kube=(kubectl --context "$profile" --request-timeout=10s)
    if [[ $1 == "--telemetry" ]]; then
        telemetry="$root/examples/telemetry"
        image=docker.io/library/radea-telemetry:lab
        mkdir "$work/telemetry"
        cp "$telemetry/Dockerfile" "$root/requirements-runtime.lock" "$work/telemetry/"
        cp -R "$root/src" "$work/telemetry/src"
        minikube --profile "$profile" image build --tag "$image" "$work/telemetry"
        built_images=$(minikube --profile "$profile" image ls)
        grep -Fxq "$image" <<< "$built_images"
        "${kube[@]}" create namespace radea-lab
        ns=("${kube[@]}" -n radea-lab)
        "${ns[@]}" create configmap radea-collector --from-file="config.yaml=$telemetry/collector.yaml"
        "${ns[@]}" apply -f "$telemetry/pod.yaml"
        "${ns[@]}" wait --for=condition=Ready pod/radea-telemetry --timeout=90s
        "${ns[@]}" exec -i pod/radea-telemetry -c capture -- python - \
            < "$root/tools/k8s_telemetry_check.py"
        exit 0
    fi
    if [[ $1 == "--operator" ]]; then
        operator_dir="$root/examples/k8s-operator"
        controller=deployment/radea-message-controller
        image=docker.io/library/radea-message-controller:lab
        mkdir "$work/operator"
        cp "$operator_dir/Dockerfile" "$root/tools/k8s_message_controller.py" "$work/operator/"
        minikube --profile "$profile" image build --tag "$image" "$work/operator"
        built_images=$(minikube --profile "$profile" image ls)
        grep -Fxq "$image" <<< "$built_images"
        "${kube[@]}" create namespace radea-lab
        radea crd-validate "$operator_dir/crd.yaml" --kubeconfig "$KUBECONFIG" --context "$profile"
        "${kube[@]}" apply -f "$operator_dir/crd.yaml"
        "${kube[@]}" wait --for=condition=Established crd/messages.lab.radea.dev --timeout=20s
        ns=("${kube[@]}" -n radea-lab)
        "${ns[@]}" apply -f "$operator_dir/controller.yaml"
        "${ns[@]}" rollout status "$controller" --timeout=45s
        account=system:serviceaccount:radea-lab:radea-message-controller
        [[ $("${ns[@]}" auth can-i get secrets --as="$account") == no ]]
        [[ $("${kube[@]}" -n default auth can-i create configmaps --as="$account") == no ]]
        "${ns[@]}" apply -f "$operator_dir/message.yaml"
        "${ns[@]}" wait --for='jsonpath={.status.observedGeneration}=1' \
            messages.lab.radea.dev/greeting --timeout=30s
        child=$("${ns[@]}" get messages.lab.radea.dev greeting -o jsonpath='{.status.configMapName}')
        expected=$("${ns[@]}" get messages.lab.radea.dev greeting -o jsonpath='{.spec.text}')
        "${ns[@]}" patch configmap "$child" --type=merge -p '{"data":{"text":"manual drift"}}'
        "${ns[@]}" wait --for="jsonpath={.data.text}=$expected" "configmap/$child" --timeout=30s
        "${ns[@]}" delete messages.lab.radea.dev greeting
        "${ns[@]}" wait --for=delete "configmap/$child" --timeout=30s
        exit 0
    fi
    if [[ $1 == "--source-to-pod" ]]; then
        # Pin the multi-platform Python base so the source build can be repeated.
        base_image=docker.io/library/python@sha256:37fc60d303cb9294d3718b5b48998a0210bb1c73611c1399ef5eb7964c0536e5
        image=docker.io/library/radea-source-to-pod:lab
        namespace=radea-source-to-pod-pr-1
        radea service-scaffold "$work/service" --name source-to-pod --base-image "$base_image"
        (cd "$work/service" && python3 -m unittest -v)
        radea dockerfile-review "$work/service/Dockerfile" --fail-on high
        minikube --profile "$profile" image build --tag "$image" "$work/service"
        built_images=$(minikube --profile "$profile" image ls)
        if ! grep -Fxq "$image" <<< "$built_images"; then
            echo "The node runtime does not contain the built service image" >&2
            exit 1
        fi
        preview=(radea preview-env --project source-to-pod --pr 1
                 --kubeconfig "$KUBECONFIG" --context "$profile")
        "${preview[@]}" up --image "$image"
        service_ip=$("${kube[@]}" -n "$namespace" get service app -o jsonpath='{.spec.clusterIP}')
        "${kube[@]}" -n "$namespace" exec deployment/app -- python -c '
import ipaddress
import json
import sys
from time import sleep
from urllib.error import URLError
from urllib.request import urlopen

address = ipaddress.ip_address(sys.argv[1])
host = f"[{address}]" if address.version == 6 else str(address)
for attempt in range(5):
    try:
        response = urlopen(f"http://{host}:8080/healthz", timeout=1)
        break
    except (URLError, TimeoutError):
        if attempt == 4:
            raise
        sleep(0.5)
with response:
    if response.status != 200 or json.load(response) != {"status": "ok"}:
        raise SystemExit("Unexpected Service response")
print("Source-to-Pod: Service returned HTTP 200 and the expected JSON")
' "$service_ip"
        "${preview[@]}" down
        "${kube[@]}" wait --for=delete "namespace/$namespace" --timeout=90s
        exit 0
    fi
    if [[ $1 == "--gateway" ]]; then
        command -v prometheus >/dev/null
        "${kube[@]}" create namespace radea-lab
        # The install includes CRDs and a production-capable Gateway API controller.
        kubectl --context "$profile" --request-timeout=120s apply --server-side \
            -f https://github.com/envoyproxy/gateway/releases/download/v1.8.6/install.yaml
        "${kube[@]}" -n envoy-gateway-system wait deployment/envoy-gateway \
            --for=condition=Available --timeout=300s
        "${kube[@]}" apply -f - <<'EOF'
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: radea-envoy
spec:
  controllerName: gateway.envoyproxy.io/gatewayclass-controller
---
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: edge
  namespace: radea-lab
spec:
  gatewayClassName: radea-envoy
  listeners:
  - name: http
    protocol: HTTP
    port: 80
EOF
        for version in stable candidate; do
            helm --kube-context "$profile" -n radea-lab upgrade --install "$version" "$chart" \
                --set replicaCount=1 --set "response=$version" --wait --timeout 240s
        done
        radea gateway-route --namespace radea-lab --gateway edge --route migration \
            --stable stable --candidate candidate --path-prefix /ready | "${kube[@]}" apply -f -
        python3 "$root/tools/k8s_gateway_check.py" "$profile" "$work"
        exit
    fi
    if [[ $1 == "--preview-ttl" ]]; then
        for project in lab other; do
            ns="radea-$project-pr-7"
            "${kube[@]}" create namespace "$ns"
            "${kube[@]}" label namespace "$ns" radea.dev/managed-preview=true \
                "radea.dev/preview-project=$project" radea.dev/preview-pr=7
        done
        "${kube[@]}" create namespace unrelated
        "${kube[@]}" label namespace unrelated radea.dev/managed-preview=true \
            radea.dev/preview-project=lab radea.dev/preview-pr=7
        sleep 2
        sweep=(radea preview-sweep --project lab --kubeconfig "$KUBECONFIG" --context "$profile"
               --older-than-seconds 1)
        "${sweep[@]}" > "$work/sweep-plan.json"
        python3 -c 'import json, sys; result = json.load(open(sys.argv[1]))
assert result["candidates"] == ["radea-lab-pr-7"] and result["deletion_requested"] == []' \
            "$work/sweep-plan.json"
        "${kube[@]}" get namespace radea-lab-pr-7
        "${sweep[@]}" --apply
        "${kube[@]}" wait --for=delete namespace/radea-lab-pr-7 --timeout=60s
        "${kube[@]}" get namespace radea-other-pr-7 unrelated
        echo "Preview TTL: planned and deleted one owned namespace; other namespaces preserved"
        exit 0
    fi

    "${kube[@]}" create namespace radea-admission
    "${kube[@]}" label namespace radea-admission lab.radea.dev/image-digest=required
    "${kube[@]}" apply -f "$root/examples/k8s-admission/image-digest.yaml"
    for namespace in radea-admission default; do
        "${kube[@]}" --namespace "$namespace" create serviceaccount image-test
    done
    pod_options=(--dry-run=server --restart=Never
                 --overrides='{"spec":{"serviceAccountName":"image-test"}}')
    admission=("${kube[@]}" --namespace radea-admission run image-test "${pod_options[@]}")
    digest=$(printf '%064d' 0)
    denied=false
    for ((attempt=0; attempt<20; attempt++)); do
        if output=$("${admission[@]}" --image=example.invalid/demo:1 2>&1); then
            sleep 1
        elif [[ $output == *"All images must use a pinned sha256 digest"* ]]; then
            denied=true
            break
        else
            echo "$output" >&2
            exit 1
        fi
    done
    $denied || { echo "Admission policy did not deny the tag-only Pod" >&2; exit 1; }
    "${admission[@]}" --image="example.invalid/demo@sha256:$digest"
    "${kube[@]}" --namespace default run image-test "${pod_options[@]}" \
        --image=example.invalid/demo:1
    echo "Admission: rejected tag-only Pod, accepted digest syntax, kept other namespaces scoped"
    if [[ $1 == "--admission" ]]; then
        python3 - "$work" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

work = Path(sys.argv[1])
manifest = b'{"schemaVersion":2}'
(work / "fixture-manifest.json").write_bytes(manifest)
(work / "fixture-claims.json").write_text(json.dumps({"critical": {
    "type": "cosign container image signature",
    "identity": {"docker-reference": "example.invalid/demo"},
    "image": {"docker-manifest-digest": "sha256:" + hashlib.sha256(manifest).hexdigest()},
}}))
PY
        openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:prime256v1 \
            -out "$work/fixture-key.pem"
        openssl pkey -in "$work/fixture-key.pem" -pubout -out "$work/fixture-pub.pem"
        openssl dgst -sha256 -sign "$work/fixture-key.pem" -out "$work/fixture.sig" \
            "$work/fixture-claims.json"
        openssl base64 -A -in "$work/fixture.sig" -out "$work/fixture.b64"
        radea image-verify "$work/fixture-manifest.json" "$work/fixture-claims.json" \
            "$work/fixture.b64" --key "$work/fixture-pub.pem" --repository example.invalid/demo \
            --admission-namespace radea-admission > "$work/verified-images.json"
        "${kube[@]}" apply -f "$work/verified-images.json"
        "${kube[@]}" label namespace radea-admission lab.radea.dev/verified-images=required
        "${kube[@]}" apply -f "$root/examples/k8s-admission/verified-images.yaml"
        denied=false
        for ((attempt=0; attempt<20; attempt++)); do
            if output=$("${admission[@]}" --image="example.invalid/demo@sha256:$digest" 2>&1); then
                sleep 1
            elif [[ $output == *"All images must be in the verified image inventory"* ]]; then
                denied=true
                break
            else
                echo "$output" >&2
                exit 1
            fi
        done
        $denied || { echo "Admission did not deny the unverified digest" >&2; exit 1; }
        verified=$("${kube[@]}" -n radea-admission get configmap radea-verified-images \
            -o jsonpath='{.data.verified}')
        "${admission[@]}" --image="$verified"
        echo "Admission: accepted the signature-verified digest and denied an unverified digest"
        exit 0
    fi

    if [[ $1 == "--preview" ]]; then
        target=(radea preview-env --project lab --kubeconfig "$KUBECONFIG" --context "$profile")
        workload=(--image docker.io/library/busybox:1.37.0 --health /hostname
                  --command httpd --command=-f --command=-p --command 8080
                  --command=-h --command /etc)
        "${target[@]}" --pr 1 up "${workload[@]}"
        "${target[@]}" --pr 2 up "${workload[@]}"
        printf '%s\n' '[{"path":"/hostname","status":200},{"path":"/radea-missing","status":404}]' \
            > "$work/preview-smoke.json"
        for pr in 1 2; do
            "${target[@]}" --pr "$pr" smoke "$work/preview-smoke.json"
            preview_namespace="radea-lab-pr-$pr"
            service_ip=$("${kube[@]}" -n "$preview_namespace" get service app \
                -o jsonpath='{.spec.clusterIP}')
            "${kube[@]}" -n "$preview_namespace" exec deploy/app -- \
                wget -T 5 -qO- "http://$service_ip:8080/hostname"
        done
        debug_kube=("${kube[@]}" -n radea-lab-pr-1)
        pod=$("${debug_kube[@]}" get pods -l app.kubernetes.io/name=preview -o name)
        "${debug_kube[@]}" get "$pod" -o json > "$work/debug-pod.json"
        debug_image=docker.io/library/busybox@sha256:a7dbc319b1438115a207e11930dc4bb3e643dcb3ec0bdd694bb36cd8fad289ec
        radea k8s-debug-plan "$work/debug-pod.json" --image "$debug_image" > "$work/debug-patch.json"
        debug_patch=("${debug_kube[@]}" patch "$pod" --subresource=ephemeralcontainers
                     --type=json --patch-file "$work/debug-patch.json")
        "${debug_patch[@]}" --dry-run=server
        "${debug_patch[@]}"
        "${debug_kube[@]}" wait \
            --for='jsonpath={.status.ephemeralContainerStatuses[0].state.terminated.exitCode}=0' \
            "$pod" --timeout=45s
        "${debug_kube[@]}" logs "$pod" -c radea-identity | grep -q 'uid=65534'
        echo "Debug: guarded ephemeral probe completed as an unprivileged user"
        if printf '%s' '{"apiVersion":"v1","kind":"DeleteOptions","preconditions":{"uid":"wrong"}}' |
            "${kube[@]}" delete --raw /api/v1/namespaces/radea-lab-pr-1 -f - \
                > "$work/wrong-uid.log" 2>&1; then
            echo "Expected the API to reject an incorrect namespace UID" >&2
            exit 1
        fi
        grep -qi precondition "$work/wrong-uid.log"
        "${target[@]}" --pr 1 down
        "${kube[@]}" wait --for=delete namespace/radea-lab-pr-1 --timeout=60s
        "${kube[@]}" -n radea-lab-pr-2 get deployment app
        "${target[@]}" --pr 1 down
        cat > "$work/closed.json" <<'EOF'
{"repository":{"full_name":"lab/fixture"},"action":"closed","number":2,
 "pull_request":{"number":2,"state":"closed","head":{"repo":{"full_name":"lab/fixture"}},
 "base":{"repo":{"full_name":"lab/fixture"}}}}
EOF
        radea preview-pr "$work/closed.json" --repository lab/fixture --project lab \
            --kubeconfig "$KUBECONFIG" --context "$profile"
        "${kube[@]}" wait --for=delete namespace/radea-lab-pr-2 --timeout=60s
        echo "Preview: two ready environments, scoped cleanup and idempotent down verified"
        exit 0
    fi

    if [[ $1 == "--gitops" ]]; then
        "${kube[@]}" create namespace radea-prune
        prune_kube=("${kube[@]}" -n radea-prune)
        "${prune_kube[@]}" create configmap unrelated --from-literal=value=kept
        mkdir "$work/origin" "$work/mirror"
        git -C "$work/origin" init -q --initial-branch=main
        git -C "$work/mirror" init -q
        git -C "$work/mirror" remote add source "$work/origin"

        publish_bundle() {
            local name separator=""
            : > "$work/origin/objects.yaml"
            for name in "$@"; do
                printf '%sapiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: %s\n' \
                    "$separator" "$name" >> "$work/origin/objects.yaml"
                printf '  namespace: radea-prune\ndata:\n  value: managed\n' \
                    >> "$work/origin/objects.yaml"
                separator=$'---\n'
            done
            git -C "$work/origin" -c core.hooksPath=/dev/null add objects.yaml
            git -C "$work/origin" -c core.hooksPath=/dev/null -c user.name=RADEA \
                -c user.email=lab@example.invalid commit --quiet --no-gpg-sign -m "Update lab bundle"
        }

        reconcile=(radea gitops-sync --repo "$work/mirror" --remote source
                   --ref refs/heads/main --manifest objects.yaml --applyset radea-inventory
                   --kubeconfig "$KUBECONFIG" --context "$profile" --namespace radea-prune)
        publish_bundle retained retired
        "${reconcile[@]}"
        "${prune_kube[@]}" get configmap retained retired
        publish_bundle retained
        "${reconcile[@]}"
        "${prune_kube[@]}" get configmap retained unrelated
        [[ -z $("${prune_kube[@]}" get configmap retired --ignore-not-found -o name) ]]
        echo "GitOps: fetched both revisions, pruned the retired member and preserved unrelated state"
        git_origin=(git -C "$work/origin" -c core.hooksPath=/dev/null -c user.name=RADEA
                    -c user.email=lab@example.invalid -c commit.gpgSign=false)
        cat > "$work/origin/workload.yaml" <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gitops-workload
  namespace: radea-prune
spec:
  replicas: 1
  selector:
    matchLabels:
      app: gitops-workload
  template:
    metadata:
      labels:
        app: gitops-workload
    spec:
      automountServiceAccountToken: false
      containers:
        - name: sample
          image: docker.io/library/busybox:1.37.0
          command: ["sleep", "3600"]
EOF
        "${git_origin[@]}" add workload.yaml
        "${git_origin[@]}" commit --quiet -m "Declare one workload replica"
        deploy_sync=(radea gitops-sync --repo "$work/mirror" --remote source
                     --ref refs/heads/main --manifest workload.yaml --allow-deployments
                     --kubeconfig "$KUBECONFIG" --context "$profile" --namespace radea-prune)
        "${deploy_sync[@]}"
        "${prune_kube[@]}" rollout status deployment/gitops-workload --timeout=60s
        sed 's/replicas: 1/replicas: 2/' "$work/origin/workload.yaml" > "$work/replicas.yaml"
        mv "$work/replicas.yaml" "$work/origin/workload.yaml"
        "${git_origin[@]}" commit --quiet -am "Scale workload to two replicas"
        "${deploy_sync[@]}"
        [[ $("${prune_kube[@]}" get deployment gitops-workload -o jsonpath='{.spec.replicas}') == 2 ]]
        "${git_origin[@]}" revert --no-edit HEAD
        "${deploy_sync[@]}"
        [[ $("${prune_kube[@]}" get deployment gitops-workload -o jsonpath='{.spec.replicas}') == 1 ]]
        echo "GitOps: applied a committed Deployment, scaled it and reverted through Git"
        exit 0
    fi

    helm_context=(--kube-context "$profile" --namespace radea-lab --timeout 2m)
    kubectl_context=(--context "$profile" --request-timeout=10s --namespace radea-lab)
    kubectl --context "$profile" --namespace kube-system rollout status deployment/coredns \
        --timeout=60s
    kubectl "${kubectl_context[@]}" create namespace radea-lab

    mkdir "$work/gitops"
    local_git=(git -C "$work/gitops" -c user.name=RADEA -c user.email=lab@example.invalid
               -c commit.gpgSign=false -c core.hooksPath=/dev/null)
    "${local_git[@]}" init --quiet
    commit_flag() {
        cat > "$work/gitops/flag.yaml" <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: radea-flags
  namespace: radea-lab
data:
  feature: "$1"
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: radea-release-state
  namespace: radea-lab
data:
  channel: stable
EOF
        "${local_git[@]}" add flag.yaml
        "${local_git[@]}" commit --quiet -m "Set feature flag to $1"
    }
    sync_flag() {
        "${local_git[@]}" show HEAD:flag.yaml > "$work/desired-flag.yaml"
        radea gitops-sync --repo "$work/gitops" --manifest flag.yaml --kubeconfig "$KUBECONFIG" \
            --context "$profile" --namespace radea-lab --force-conflicts
    }
    check_flag_drift() {
        kubectl "${kubectl_context[@]}" get -f "$work/desired-flag.yaml" -o json \
            > "$work/observed-flag.json" || return 1
        radea k8s-drift "$work/desired-flag.yaml" "$work/observed-flag.json" --fail-on-drift
    }
    commit_flag disabled
    sync_flag

    helm upgrade --install radea-lab "$chart" "${helm_context[@]}" --atomic
    helm test radea-lab "${helm_context[@]}"
    helm upgrade radea-lab "$chart" "${helm_context[@]}" --set replicaCount=3 --atomic
    replicas=$(kubectl "${kubectl_context[@]}" get deployment radea-lab -o jsonpath='{.spec.replicas}')
    [[ $replicas == 3 ]]
    helm test radea-lab "${helm_context[@]}"
    helm rollback radea-lab 1 "${helm_context[@]}" --wait
    helm test radea-lab "${helm_context[@]}"
    replicas=$(kubectl "${kubectl_context[@]}" get deployment radea-lab -o jsonpath='{.spec.replicas}')
    [[ $replicas == 2 ]]
    kubectl "${kubectl_context[@]}" get pods -l app.kubernetes.io/instance=radea-lab -o json \
        > "$work/pods.json"
    captured_pod=$(kubectl "${kubectl_context[@]}" get pods \
        -l app.kubernetes.io/instance=radea-lab -o jsonpath='{.items[0].metadata.name}')
    radea k8s-capture "$captured_pod" --namespace radea-lab --context "$profile" \
        --kubeconfig "$KUBECONFIG" --container http > "$work/pod-capture.json"
    python3 -c 'import json, sys; report = json.load(open(sys.argv[1]))
assert report["summary"]["pods"] == 1 and not report["warnings"]
assert report["logs"]["container"] == "http"
print("Read-only capture: Pod status, events and selected logs verified")' "$work/pod-capture.json"
    radea k8s-health "$work/pods.json" --fail-on-signal
    helm template radea-lab "$chart" --namespace radea-lab --skip-tests > "$work/desired.yaml"
    kubectl "${kubectl_context[@]}" get -f "$work/desired.yaml" -o json > "$work/observed.json"
    radea k8s-drift "$work/desired.yaml" "$work/observed.json" --fail-on-drift

    fetch() {
        kubectl "${kubectl_context[@]}" exec deploy/radea-lab -- \
            wget -T 3 -qO- "http://$1:8080/${2:-ready}"
    }

    wait_for_response() {
        local service=$1 expected=$2 path=${3:-ready} attempts=${4:-20} response attempt streak=0
        for ((attempt=0; attempt<attempts; attempt++)); do
            if response=$(fetch "$service" "$path" 2>/dev/null) && [[ "$response" == "$expected" ]]; then
                streak=$((streak + 1))
                if [[ $streak == 3 ]]; then
                    echo "$service returned $expected on three consecutive requests"
                    return 0
                fi
            else
                streak=0
            fi
            sleep 1
        done
        echo "$service did not converge to $expected" >&2
        return 1
    }

    route_active() {
        kubectl "${kubectl_context[@]}" patch service radea-active --type=json \
            -p "[{\"op\":\"replace\",\"path\":\"/spec/selector\",\"value\":$1}]"
    }

    stable_selector='{"app.kubernetes.io/instance":"radea-lab"}'
    preview_selector='{"app.kubernetes.io/instance":"radea-preview"}'
    mixed_selector='{"app.kubernetes.io/name":"radea-lab"}'
    helm upgrade radea-lab "$chart" "${helm_context[@]}" --set replicaCount=4 --atomic
    helm upgrade --install radea-preview "$chart" "${helm_context[@]}" \
        --set replicaCount=1 --set-string response=radea-preview --atomic
    kubectl "${kubectl_context[@]}" expose deployment radea-lab --name=radea-active --port=8080
    wait_for_response radea-active radea-ok
    helm test radea-preview "${helm_context[@]}"
    wait_for_response radea-preview radea-preview

    echo "Canary: temporarily select both verified releases"
    route_active "$mixed_selector"
    stable_seen=false
    preview_seen=false
    for ((attempt=0; attempt<30; attempt++)); do
        if response=$(fetch radea-active); then
            case "$response" in
                radea-ok) stable_seen=true ;;
                radea-preview) preview_seen=true ;;
                *) echo "Unrecognized canary response" >&2; exit 1 ;;
            esac
        fi
        if $stable_seen && $preview_seen; then
            break
        fi
        sleep 1
    done
    $stable_seen && $preview_seen || { echo "Canary did not serve both releases" >&2; exit 1; }
    echo "Canary: both releases served traffic"

    gate_traffic() {
        local path=$1 decision=0
        python3 "$root/tools/k8s_canary_samples.py" --context "$profile" --path "$path" \
            > "$work/canary.json" || return 1
        radea canary-gate "$work/canary.json" --min-requests 8 --min-success-rate 1 \
            --max-p95-ms 5000 || decision=$?
        case $decision in
            0) route_active "$preview_selector" ;;
            2) route_active "$stable_selector" ;;
            *) echo "Canary gate could not make a rollout decision" >&2; return 1 ;;
        esac || return 1
    }

    echo "Canary gate: inject failures through a missing preview endpoint"
    gate_traffic missing
    wait_for_response radea-active radea-ok
    echo "Canary gate: evaluate the healthy preview endpoint"
    route_active "$mixed_selector"
    gate_traffic ready
    wait_for_response radea-active radea-preview
    echo "Blue-green: route back to the stable release"
    route_active "$stable_selector"
    wait_for_response radea-active radea-ok
    if [[ $1 == "--canary" ]]; then
        exit 0
    fi

    operator_examples="$root/examples/k8s-operator"
    operator=(python3 "$root/tools/k8s_message_controller.py" --kubeconfig "$KUBECONFIG"
              --context "$profile" --namespace radea-lab --once)
    crd=messages.lab.radea.dev
    radea crd-validate "$operator_examples/crd.yaml" --kubeconfig "$KUBECONFIG" --context "$profile"
    sed 's/type: string/type: invalid-schema-type/g' "$operator_examples/crd.yaml" > "$work/bad-crd.yaml"
    validation_status=0
    radea crd-validate "$work/bad-crd.yaml" --kubeconfig "$KUBECONFIG" --context "$profile" \
        > "$work/bad-crd.json" || validation_status=$?
    [[ $validation_status == 2 ]]
    grep -q 'invalid-schema-type' "$work/bad-crd.json"
    persisted_crd=$(kubectl "${kubectl_context[@]}" get "crd/$crd" --ignore-not-found -o name)
    [[ -z $persisted_crd ]]
    kubectl "${kubectl_context[@]}" apply -f "$operator_examples/crd.yaml"
    kubectl "${kubectl_context[@]}" wait --for=condition=Established "crd/$crd" --timeout=10s
    kubectl "${kubectl_context[@]}" apply -f "$operator_examples/message.yaml"
    if kubectl "${kubectl_context[@]}" patch "$crd" greeting --type=merge \
            -p '{"spec":{"text":42}}' --dry-run=server > "$work/invalid-cr.log" 2>&1; then
        echo "CRD accepted a numeric message" >&2
        exit 1
    fi
    if ! grep -q 'spec.text' "$work/invalid-cr.log"; then
        cat "$work/invalid-cr.log" >&2
        exit 1
    fi
    "${operator[@]}"
    child=$(kubectl "${kubectl_context[@]}" get "$crd" greeting -o jsonpath='{.status.configMapName}')
    [[ -n $child ]]
    child_text() {
        kubectl "${kubectl_context[@]}" get configmap "$child" -o jsonpath='{.data.text}'
    }
    [[ $(child_text) == hello-from-radea ]]
    kubectl "${kubectl_context[@]}" patch configmap "$child" --type=merge \
        -p '{"data":{"text":"out-of-band"}}'
    "${operator[@]}"
    [[ $(child_text) == hello-from-radea ]]
    kubectl "${kubectl_context[@]}" patch "$crd" greeting --type=merge \
        -p '{"spec":{"text":"updated-message"}}'
    "${operator[@]}"
    [[ $(child_text) == updated-message ]]
    generation=$(kubectl "${kubectl_context[@]}" get "$crd" greeting \
        -o jsonpath='{.metadata.generation}')
    observed=$(kubectl "${kubectl_context[@]}" get "$crd" greeting \
        -o jsonpath='{.status.observedGeneration}')
    [[ "$generation" == "$observed" ]]
    kubectl "${kubectl_context[@]}" delete "$crd" greeting --cascade=foreground --timeout=15s
    [[ -z $(kubectl "${kubectl_context[@]}" get configmap "$child" --ignore-not-found -o name) ]]
    echo "Controller: schema, create, drift repair, update, status and owner cleanup verified"

    # Both writes affect a single ConfigMap in the disposable namespace.
    deployment_generation() {
        kubectl "${kubectl_context[@]}" get deployment radea-lab \
            -o jsonpath='{.metadata.generation}'
    }
    generation_before=$(deployment_generation)
    wait_for_response radea-active disabled flags/feature
    commit_flag enabled
    sync_flag
    wait_for_response radea-active enabled flags/feature 100
    check_flag_drift
    kubectl "${kubectl_context[@]}" patch configmap radea-flags --type=merge \
        -p '{"data":{"feature":"manual-drift"}}'
    if check_flag_drift; then
        echo "Expected drift after a manual change" >&2
        exit 1
    else
        [[ $? == 2 ]]
    fi
    sync_flag
    check_flag_drift
    "${local_git[@]}" revert --no-edit HEAD
    sync_flag
    check_flag_drift
    wait_for_response radea-active disabled flags/feature 100
    [[ $(deployment_generation) == "$generation_before" ]]
    echo "GitOps: commit, drift repair and Git revert verified; Deployment generation unchanged"
fi
