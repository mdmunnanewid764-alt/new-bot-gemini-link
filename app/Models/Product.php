<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Builder;

class Product extends Model
{
    use HasFactory;

    protected $fillable = [
        'supplier_product_id',
        'category_id',
        'name',
        'description',
        'sell_price',
        'cost_price',
        'stock_count',
        'in_stock',
        'is_enabled',
        'synced_at',
    ];

    protected $casts = [
        'sell_price' => 'float',
        'cost_price' => 'float',
        'stock_count' => 'integer',
        'in_stock' => 'boolean',
        'is_enabled' => 'boolean',
        'synced_at' => 'datetime',
    ];

    /**
     * Scope to filter available products (enabled + in-stock).
     */
    public function scopeAvailable(Builder $query): Builder
    {
        return $query->where('is_enabled', true)
                     ->where('in_stock', true);
    }

    /**
     * Category Relationship.
     */
    public function category()
    {
        return $this->belongsTo(Category::class);
    }

    /**
     * Check if product stock is unlimited.
     */
    public function isUnlimitedStock(): bool
    {
        return is_null($this->stock_count);
    }

    /**
     * Helper to format price string.
     */
    public function getFormattedPriceAttribute(): string
    {
        return '$' . number_format($this->sell_price, 2);
    }
}
