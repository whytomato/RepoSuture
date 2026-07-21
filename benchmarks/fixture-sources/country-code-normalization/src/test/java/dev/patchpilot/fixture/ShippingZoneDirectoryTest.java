package dev.patchpilot.fixture;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

class ShippingZoneDirectoryTest {
    private final ShippingZoneDirectory directory =
            new ShippingZoneDirectory(new CountryCodeNormalizer());

    @Test
    void acceptsEquivalentDomesticCountryCodes() {
        assertTrue(directory.isDomestic(" us "));
    }

    @Test
    void rejectsForeignCountryCode() {
        assertFalse(directory.isDomestic("CA"));
    }

    @Test
    void acceptsCanonicalDomesticCountryCode() {
        assertTrue(directory.isDomestic("US"));
    }
}
