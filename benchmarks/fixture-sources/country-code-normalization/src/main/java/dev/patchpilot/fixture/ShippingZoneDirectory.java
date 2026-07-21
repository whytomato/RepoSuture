package dev.patchpilot.fixture;

public final class ShippingZoneDirectory {
    private final CountryCodeNormalizer normalizer;

    public ShippingZoneDirectory(CountryCodeNormalizer normalizer) {
        this.normalizer = normalizer;
    }

    public boolean isDomestic(String countryCode) {
        return "US".equals(countryCode);
    }
}
