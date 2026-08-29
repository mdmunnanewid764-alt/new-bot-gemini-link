<?php

namespace App\Services;

use App\Models\Product;
use App\Models\ProductSyncLog;
use App\Events\PriceChanged;
use App\Events\StockUpdated;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Log;
use Exception;

class ProductSyncService
{
    /**
     * Synchronize remote products into local database catalog.
     *
     * @param array $remoteProducts Array of product objects from Shop API /products
     * @return ProductSyncLog Audit log of the synchronization operation
     */
    public function syncProducts(array $remoteProducts): ProductSyncLog
    {
        $itemsAdded = 0;
        $itemsUpdated = 0;
        $changesSummary = [];
        $syncedProductIds = [];

        DB::beginTransaction();

        try {
            foreach ($remoteProducts as $item) {
                $supplierId = $item['id'] ?? $item['product_id'] ?? null;
                if (!$supplierId) {
                    continue;
                }

                $syncedProductIds[] = $supplierId;

                $name = $item['name'] ?? 'Digital Product';
                $price = floatval($item['sell_price'] ?? 0.0);
                $stockCount = isset($item['stock_count']) ? (is_null($item['stock_count']) ? null : intval($item['stock_count'])) : null;
                $inStock = boolval($item['in_stock'] ?? true);

                $product = Product::where('supplier_product_id', $supplierId)->first();

                if (!$product) {
                    // Create new product
                    $product = Product::create([
                        'supplier_product_id' => $supplierId,
                        'name' => $name,
                        'sell_price' => $price,
                        'stock_count' => $stockCount,
                        'in_stock' => $inStock,
                        'is_enabled' => true,
                        'synced_at' => now(),
                    ]);

                    $itemsAdded++;
                    $changesSummary[] = [
                        'type' => 'created',
                        'product_id' => $product->id,
                        'name' => $name,
                        'price' => $price,
                    ];
                } else {
                    $hasChange = false;

                    // Price Change Detection
                    if (abs($product->sell_price - $price) > 0.0001) {
                        event(new PriceChanged($product, $product->sell_price, $price));
                        $changesSummary[] = [
                            'type' => 'price_changed',
                            'product_id' => $product->id,
                            'name' => $name,
                            'old_price' => $product->sell_price,
                            'new_price' => $price,
                        ];
                        $product->sell_price = $price;
                        $hasChange = true;
                    }

                    // Stock Change Detection
                    if ($product->stock_count !== $stockCount || $product->in_stock !== $inStock) {
                        event(new StockUpdated($product, $product->stock_count, $stockCount));
                        $changesSummary[] = [
                            'type' => 'stock_updated',
                            'product_id' => $product->id,
                            'name' => $name,
                            'old_stock' => $product->stock_count,
                            'new_stock' => $stockCount,
                        ];
                        $product->stock_count = $stockCount;
                        $product->in_stock = $inStock;
                        $hasChange = true;
                    }

                    $product->name = $name;
                    $product->synced_at = now();
                    $product->save();

                    if ($hasChange) {
                        $itemsUpdated++;
                    }
                }
            }

            // Deactivate local items no longer in supplier catalog
            Product::whereNotIn('supplier_product_id', $syncedProductIds)
                ->update(['in_stock' => false]);

            DB::commit();

            // Flush catalog cache
            Cache::forget('catalog:available_products');

            $log = ProductSyncLog::create([
                'status' => 'success',
                'items_synced' => count($syncedProductIds),
                'items_added' => $itemsAdded,
                'items_updated' => $itemsUpdated,
                'changes_summary' => $changesSummary,
            ]);

            Log::info("Product Sync completed successfully. Added: {$itemsAdded}, Updated: {$itemsUpdated}");
            return $log;

        } catch (Exception $e) {
            DB::rollBack();
            Log::error("Product Sync failed: " . $e->getMessage());

            return ProductSyncLog::create([
                'status' => 'failed',
                'items_synced' => count($syncedProductIds),
                'items_added' => $itemsAdded,
                'items_updated' => $itemsUpdated,
                'error_message' => $e->getMessage(),
            ]);
        }
    }
}
