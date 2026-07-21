package dev.patchpilot.fixture;

import java.util.List;

public final class TicketService {
    private final TicketVisibilityPolicy visibilityPolicy;

    public TicketService(TicketVisibilityPolicy visibilityPolicy) {
        this.visibilityPolicy = visibilityPolicy;
    }

    public List<Ticket> activeTickets(List<Ticket> tickets) {
        return tickets.stream().filter(visibilityPolicy::isActive).toList();
    }
}
