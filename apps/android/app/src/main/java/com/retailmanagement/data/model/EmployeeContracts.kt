package com.retailmanagement.data.model

import com.google.gson.annotations.SerializedName

data class StoreEmployeeRead(
    val id: String,
    @SerializedName("role_id") val roleId: String,
    @SerializedName("full_name") val fullName: String,
    val email: String,
    val phone: String? = null,
    val role: String
) {
    val username: String
        get() = email.substringBefore("@")
}

data class SearchedUser(
    val id: String,
    val email: String,
    @SerializedName("full_name") val fullName: String,
    @SerializedName("firebase_uid") val firebaseUid: String
) {
    val username: String
        get() = email.substringBefore("@")
}

data class UserStoreRoleCreate(
    @SerializedName("user_id") val userId: String,
    @SerializedName("store_id") val storeId: String,
    val role: String
)

data class UserStoreRoleUpdate(
    val role: String
)
