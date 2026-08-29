<?php

namespace App\Jobs;

use App\Services\ProductSyncService;
use Illuminate\Bus\Queueable;
use Illuminate\Contracts\Queue\ShouldQueue;
use Illuminate\Foundation\Bus\Dispatchable;
use Illuminate\Queue\InteractsWithQueue;
use Illuminate\Queue\SerializesModels;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Log;
use Exception;

class SyncProductsJob implements ShouldQueue
{
    use Dispatchable, InteractsWithQueue, Queueable, SerializesModels;

    public int $tries = 3;
    public int $backoff = 10;

    /**
     * Execute the job.
     */
    public function handle(ProductSyncService $syncService): void
    {
        $baseUrl = config('services.shop_api.base_url', 'https://upibot.00969600.xyz/shop-api/v1');
        $apiKey = config('services.shop_api.key', env('SHOP_API_KEY'));

        if (!$apiKey) {
            Log::warning('SyncProductsJob skipped: SHOP_API_KEY is not set.');
            return;
        }

        try {
            $response = Http::withHeaders([
                'X-Shop-API-Key' => $apiKey,
                'Content-Type' => 'application/json',
            ])->timeout(15)->get("{$baseUrl}/products");

            if ($response->successful()) {
                $data = $response->json();
                $products = $data['products'] ?? [];
                $log = $syncService->syncProducts($products);
                Log::info("SyncProductsJob completed: Synced {$log->items_synced} products.");
            } else {
                Log::error("SyncProductsJob API Request failed: " . $response->status() . " " . $response->body());
            }
        } catch (Exception $e) {
            Log::error("SyncProductsJob Exception: " . $e->getMessage());
            throw $e;
        }
    }
}
