/** @odoo-module **/

/**
 * Odoo 17 compatibility shim for Home Screen Theme.
 *
 * Odoo 18 introduced `@web/core/user` (a `user` singleton) and
 * `@web/core/network/rpc` (a standalone `rpc()` function). Neither exists in
 * Odoo 17, so this module reproduces that small API on top of Odoo 17
 * primitives, letting the theme code keep importing `{ user, rpc }` unchanged.
 *
 *   - rpc   -> `jsonrpc` from `@web/core/network/rpc_service` (same signature).
 *   - user  -> a singleton backed by `@web/session`, matching the subset of the
 *              Odoo 18 `user` API the theme actually uses
 *              (userId, name, lang, context, settings, setUserSettings).
 */
import { session } from "@web/session";
import { jsonrpc } from "@web/core/network/rpc_service";

// Same call signature as Odoo 18's rpc(url, params, settings).
export const rpc = jsonrpc;

// Snapshot the user settings at import time: the core userService deletes
// `session.user_settings` when it starts (which happens after all module JS is
// imported), so copying it now keeps it available like Odoo 18's user.settings.
const _settings =
    session.user_settings && typeof session.user_settings === "object"
        ? { ...session.user_settings }
        : {};

export const user = {
    get userId() {
        return session.uid ?? session.user_id;
    },
    get partnerId() {
        return session.partner_id;
    },
    get name() {
        return session.name;
    },
    get context() {
        return session.user_context || {};
    },
    get lang() {
        return (session.user_context || {}).lang;
    },
    get settings() {
        return _settings;
    },
    async setUserSettings(key, value) {
        const changed = await jsonrpc(
            "/web/dataset/call_kw/res.users.settings/set_res_users_settings",
            {
                model: "res.users.settings",
                method: "set_res_users_settings",
                args: [[_settings.id]],
                kwargs: { new_settings: { [key]: value } },
            }
        );
        if (changed && typeof changed === "object") {
            Object.assign(_settings, changed);
        }
        return changed;
    },
};
