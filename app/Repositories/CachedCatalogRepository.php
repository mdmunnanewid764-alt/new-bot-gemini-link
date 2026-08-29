<?php

namespace App\Repositories;

use App\Models\Product;
use Illuminate\Support\Collection;
use Illuminate\Support\Facades\Cache;

class CachedCatalogRepository implements CatalogRepositoryInterface
{
    protected CatalogRepositoryInterface $repository;
    protected int $ttl;

    public function __construct(CatalogRepositoryInterface $repository, int $ttl = 300)
    {
        $this->repository = $repository;
        $this->ttl = $ttl; // 5 minutes default cache duration
    }

    public function getAvailableProducts(): Collection
    {
        return Cache::remember('catalog:available_products', $this->ttl, function () {
            return $this->repository->getAvailableProducts();
        });
    }

    public function findProduct(int $id): ?Product
    {
        return Cache::remember("catalog:product:{$id}", $this->ttl, function () use ($id) {
            return $this->repository->findProduct($id);
        });
    }

    public function clearCache(): void
    {
        Cache::forget('catalog:available_products');
    }
}
