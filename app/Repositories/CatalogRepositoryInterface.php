<?php

namespace App\Repositories;

use App\Models\Product;
use Illuminate\Support\Collection;

interface CatalogRepositoryInterface
{
    /**
     * Get all available products (enabled & in stock).
     *
     * @return Collection<Product>
     */
    public function getAvailableProducts(): Collection;

    /**
     * Find product by local ID or supplier product ID.
     *
     * @param int $id
     * @return Product|null
     */
    public function findProduct(int $id): ?Product;

    /**
     * Flush/clear catalog cache.
     */
    public function clearCache(): void;
}
