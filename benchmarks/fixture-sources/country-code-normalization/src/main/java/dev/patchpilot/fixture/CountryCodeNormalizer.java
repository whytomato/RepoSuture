package dev.patchpilot.fixture;

import java.util.Locale;

public final class CountryCodeNormalizer {
    public String normalize(String countryCode) {
        return countryCode.trim().toUpperCase(Locale.ROOT);
    }
}
