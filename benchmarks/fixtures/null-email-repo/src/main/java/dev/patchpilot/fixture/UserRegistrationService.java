package dev.patchpilot.fixture;

import java.util.Locale;

public final class UserRegistrationService {
    public RegisteredUser register(String username, String email) {
        if (email.isBlank()) {
            throw new InvalidEmailException("email must not be blank");
        }
        return new RegisteredUser(username.trim(), email.trim().toLowerCase(Locale.ROOT));
    }
}

