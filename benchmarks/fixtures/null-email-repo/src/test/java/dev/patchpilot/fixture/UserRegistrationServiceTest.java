package dev.patchpilot.fixture;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import org.junit.jupiter.api.Test;

class UserRegistrationServiceTest {
    private final UserRegistrationService service = new UserRegistrationService();

    @Test
    void shouldRejectNullEmail() {
        InvalidEmailException error = assertThrows(
                InvalidEmailException.class,
                () -> service.register("Ada", null));

        assertEquals("email must not be blank", error.getMessage());
    }

    @Test
    void shouldNormalizeAValidEmail() {
        RegisteredUser user = service.register(" Ada ", " ADA@EXAMPLE.COM ");

        assertEquals("Ada", user.username());
        assertEquals("ada@example.com", user.email());
    }

    @Test
    void shouldRejectBlankEmail() {
        InvalidEmailException error = assertThrows(
                InvalidEmailException.class,
                () -> service.register("Ada", "   "));

        assertEquals("email must not be blank", error.getMessage());
    }
}

