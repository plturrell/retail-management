package com.retailmanagement.data.model

import com.google.gson.annotations.SerializedName

// ── Orders ──

enum class OrderStatus(val display: String) {
    @SerializedName("open")      OPEN("Open"),
    @SerializedName("completed") COMPLETED("Completed"),
    @SerializedName("voided")    VOIDED("Voided");

    companion object {
        fun fromString(v: String) = entries.firstOrNull { it.name.equals(v, ignoreCase = true) } ?: OPEN
    }
}

enum class OrderSource(val display: String) {
    @SerializedName("nec_pos")    NEC_POS("NEC POS"),
    @SerializedName("hipay")      HIPAY("HiPay"),
    @SerializedName("airwallex")  AIRWALLEX("Airwallex"),
    @SerializedName("shopify")    SHOPIFY("Shopify"),
    @SerializedName("manual")     MANUAL("Manual");

    companion object {
        fun fromString(v: String) = entries.firstOrNull { it.name.equals(v, ignoreCase = true) }
            ?: entries.firstOrNull { it.name.replace("_","").equals(v.replace("_",""), ignoreCase = true) }
            ?: MANUAL
    }
}

data class OrderItem(
    val id: String,
    @SerializedName("order_id")  val orderId: String,
    @SerializedName("sku_id")    val skuId: String,
    val qty: Int,
    @SerializedName("unit_price") val unitPrice: Double,
    val discount: Double = 0.0,
    @SerializedName("line_total") val lineTotal: Double,
    @SerializedName("created_at") val createdAt: String? = null
)

data class Order(
    val id: String,
    @SerializedName("order_number")  val orderNumber: String,
    @SerializedName("store_id")      val storeId: String,
    @SerializedName("staff_id")      val staffId: String? = null,
    @SerializedName("order_date")    val orderDate: String,
    val subtotal: Double,
    @SerializedName("discount_total") val discountTotal: Double = 0.0,
    @SerializedName("tax_total")     val taxTotal: Double = 0.0,
    @SerializedName("grand_total")   val grandTotal: Double,
    @SerializedName("payment_method") val paymentMethod: String,
    @SerializedName("payment_ref")   val paymentRef: String? = null,
    val status: String,         // raw string, parse with OrderStatus.fromString()
    val source: String,         // raw string, parse with OrderSource.fromString()
    val items: List<OrderItem> = emptyList(),
    @SerializedName("created_at") val createdAt: String? = null,
    @SerializedName("updated_at") val updatedAt: String? = null
) {
    val orderStatus get() = OrderStatus.fromString(status)
    val orderSource get() = OrderSource.fromString(source)
    val itemCount get() = items.sumOf { it.qty }
    val formattedTotal get() = String.format("$%.2f", grandTotal)
}
