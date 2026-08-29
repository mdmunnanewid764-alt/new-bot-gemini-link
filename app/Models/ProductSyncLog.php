<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class ProductSyncLog extends Model
{
    protected $fillable = [
        'status',
        'items_synced',
        'items_added',
        'items_updated',
        'changes_summary',
        'error_message',
    ];

    protected $casts = [
        'items_synced' => 'integer',
        'items_added' => 'integer',
        'items_updated' => 'integer',
        'changes_summary' => 'array',
    ];
}
