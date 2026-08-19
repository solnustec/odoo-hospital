/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { NavBar } from "@web/webclient/navbar/navbar";

patch(NavBar.prototype, {
    get currentApp() {
        const hm = this.env.services.home_menu;
        if (hm?.hasHomeMenu) {
            return;
        }
        return super.currentApp;
    },
    get currentAppSections() {
        const hm = this.env.services.home_menu;
        if (hm?.hasHomeMenu) {
            return [];
        }
        return super.currentAppSections;
    },
    // NOTE (Odoo 17): the v18 navbar methods _openAppMenuSidebar() /
    // onAllAppsBtnClick() / _closeAppMenuSidebar() do not exist here — the
    // Odoo 17 navbar uses a classic apps-menu <Dropdown>. The Home toggle is
    // driven directly from the template (home_theme.NavBar.AppsMenu), which
    // replaces that dropdown with the Home/back arrow button.
});
