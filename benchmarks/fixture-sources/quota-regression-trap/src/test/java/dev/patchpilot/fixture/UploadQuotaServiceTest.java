package dev.patchpilot.fixture;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

class UploadQuotaServiceTest {
    private final UploadQuotaService service = new UploadQuotaService();

    @Test
    void grantsPremiumUploadQuota() {
        assertEquals(100, service.quotaFor(Plan.PREMIUM, false));
    }

    @Test
    void preservesStandardUploadQuota() {
        assertEquals(20, service.quotaFor(Plan.STANDARD, false));
    }

    @Test
    void trialQuotaOverridesPlanQuota() {
        assertEquals(5, service.quotaFor(Plan.PREMIUM, true));
    }
}
