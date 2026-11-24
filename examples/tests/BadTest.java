import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class BadTest {
    @Test
    void noAssertion() {
        service().run();
    }

    @Test
    void alwaysTrue() {
        assertTrue(true);
    }

    @Test
    void emptyBody() {
    }

    @Test
    void swallows() {
        try {
            service().run();
        } catch (Exception e) {}
    }

    Service service() { return new Service(); }
    static class Service { void run() {} }
}
