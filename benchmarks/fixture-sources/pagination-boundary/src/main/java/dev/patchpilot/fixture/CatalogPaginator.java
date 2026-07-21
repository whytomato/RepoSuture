package dev.patchpilot.fixture;

import java.util.List;

public final class CatalogPaginator {
    public List<String> page(List<String> items, int pageNumber, int pageSize) {
        if (pageNumber < 1 || pageSize < 1) {
            throw new IllegalArgumentException("pageNumber and pageSize must be positive");
        }

        int fromIndex = (pageNumber - 1) * pageSize;
        if (fromIndex >= items.size()) {
            return List.of();
        }
        int toIndex = Math.min(fromIndex + pageSize - 1, items.size());
        return List.copyOf(items.subList(fromIndex, toIndex));
    }
}
