package dev.patchpilot.fixture;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.util.List;
import org.junit.jupiter.api.Test;

class TicketServiceTest {
    private final TicketService service = new TicketService(new TicketVisibilityPolicy());

    @Test
    void includesWorkInProgressAmongActiveTickets() {
        List<Ticket> tickets = List.of(
                new Ticket("T-1", TicketStatus.OPEN),
                new Ticket("T-2", TicketStatus.IN_PROGRESS));

        assertEquals(List.of("T-1", "T-2"), ids(service.activeTickets(tickets)));
    }

    @Test
    void excludesClosedTickets() {
        List<Ticket> tickets = List.of(
                new Ticket("T-1", TicketStatus.CLOSED),
                new Ticket("T-2", TicketStatus.OPEN));

        assertEquals(List.of("T-2"), ids(service.activeTickets(tickets)));
    }

    private static List<String> ids(List<Ticket> tickets) {
        return tickets.stream().map(Ticket::id).toList();
    }
}
