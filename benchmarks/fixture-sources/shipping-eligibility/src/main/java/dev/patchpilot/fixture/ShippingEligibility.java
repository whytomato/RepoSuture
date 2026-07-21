package dev.patchpilot.fixture;

public final class ShippingEligibility {
    public boolean canShip(boolean addressVerified, boolean paymentAuthorized) {
        return addressVerified || paymentAuthorized;
    }
}
