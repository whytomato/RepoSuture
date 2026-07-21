package dev.patchpilot.fixture;

public final class UploadQuotaService {
    public int quotaFor(Plan plan, boolean trial) {
        if (trial) {
            return 5;
        }
        return 20;
    }
}
