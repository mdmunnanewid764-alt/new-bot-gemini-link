<?php

namespace App\Repositories;

use App\Models\Product;
use Illuminate\Support\Collection;

class CatalogRepository implements CatalogRepositoryInterface
{
    public function getAvailableProducts(): Collection
    {
        return Product::available()->orderBy('sell_price', 'asc')->get();
    }

    public function findProduct(int $id): ?Product
    {
        return Product::where('id', $id)
            ->orWhere('supplier_product_id', $id)
            ->first();
    }

    public function clearCache(): void
    {
        // Concrete DB repository does not handle caching
    }
}
