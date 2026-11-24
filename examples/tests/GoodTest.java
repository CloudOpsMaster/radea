import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class GoodTest {
    @Test
    void checksResult() {
        assertEquals(3, 1 + 2);
    }

    @Test
    void throwsOnBadInput() {
        assertThrows(IllegalArgumentException.class, () -> { throw new IllegalArgumentException(); });
    }

    @Test(expected = IllegalStateException.class)
    void legacyExpected() {
        throw new IllegalStateException();
    }
}
