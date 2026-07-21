package dev.patchpilot.fixture;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.util.List;
import org.junit.jupiter.api.Test;

class CatalogPaginatorTest {
    private final CatalogPaginator paginator = new CatalogPaginator();

    @Test
    void returnsCompletePageAtBoundary() {
        List<String> page = paginator.page(List.of("alpha", "beta", "gamma"), 1, 2);

        assertEquals(List.of("alpha", "beta"), page);
    }

    @Test
    void returnsEmptyPageAfterLastItem() {
        assertEquals(List.of(), paginator.page(List.of("alpha", "beta"), 3, 2));
    }

    @Test
    void rejectsNonPositivePageSize() {
        assertThrows(
                IllegalArgumentException.class,
                () -> paginator.page(List.of("alpha"), 1, 0));
    }
}
