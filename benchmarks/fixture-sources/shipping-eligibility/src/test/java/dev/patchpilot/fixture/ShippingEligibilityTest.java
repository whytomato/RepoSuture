package dev.patchpilot.fixture;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

class ShippingEligibilityTest {
    private final ShippingEligibility eligibility = new ShippingEligibility();

    @Test
    void requiresAddressAndPaymentApproval() {
        assertFalse(eligibility.canShip(true, false));
        assertFalse(eligibility.canShip(false, true));
    }

    @Test
    void allowsFullyApprovedShipment() {
        assertTrue(eligibility.canShip(true, true));
    }

    @Test
    void rejectsShipmentWithNoApproval() {
        assertFalse(eligibility.canShip(false, false));
    }
}
