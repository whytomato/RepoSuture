package dev.patchpilot.fixture;

public final class TicketVisibilityPolicy {
    public boolean isActive(Ticket ticket) {
        return ticket.status() != TicketStatus.CLOSED
                && ticket.status() != TicketStatus.IN_PROGRESS;
    }
}
