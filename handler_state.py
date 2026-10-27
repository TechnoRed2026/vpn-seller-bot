"""Shared conversation state for Telegram handlers."""

S_TRAFFIC_EMAIL = "traffic_email"
S_CREATE_EMAIL = "create_email"
S_CREATE_USER_ID = "create_user_id"
S_CREATE_GB = "create_gb"
S_CREATE_DAYS = "create_days"
S_ASK_INSECURE = "ask_insecure"
S_ADD_TRAFFIC = "add_traffic"
S_EDIT_GB = "edit_gb"
S_EDIT_DAYS = "edit_days"
S_WALLET_AMOUNT = "wallet_amount"
S_WALLET_PHOTO = "wallet_photo"
S_SHOP_NAME = "shop_name"
S_SHOP_GB = "shop_gb"
S_SHOP_CUSTOM_GB = "shop_custom_gb"
S_SHOP_DAYS = "shop_days"
S_RENEW_GB = "renew_gb"
S_RENEW_CUSTOM_GB = "renew_custom_gb"
S_WG_NAME = "wg_name"
S_WG_USER_ID = "wg_user_id"
S_WG_GB = "wg_gb"
S_BL_IDENTIFIER = "blacklist_identifier"
S_BL_USER_ID = "blacklist_user_id"
S_BL_REASON = "blacklist_reason"
S_BL_REMOVE_USER_ID = "blacklist_remove_user_id"

states: dict[int, str | None] = {}
data: dict[int, dict] = {}


def clear_state(uid: int) -> None:
    states.pop(uid, None)
    data.pop(uid, None)
