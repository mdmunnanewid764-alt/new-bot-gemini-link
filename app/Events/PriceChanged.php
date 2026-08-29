<?php

namespace App\Events;

use App\Models\Product;
use Illuminate\Foundation\Events\Dispatchable;
use Illuminate\Queue\SerializesModels;

class PriceChanged
{
    use Dispatchable, SerializesModels;

    public Product $product;
    public float $oldPrice;
    public float $newPrice;

    public function __construct(Product $product, float $oldPrice, float $newPrice)
    {
        $this->product = $product;
        $this->oldPrice = $oldPrice;
        $this->newPrice = $newPrice;
    }
}
