/** @odoo-module */

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";

const CONNECTION_TIMEOUT_MS = 45000;
const SUCCESS_DISPLAY_MS = 2000;

class WhatsappQrAction extends Component {
    static template = "hospital_chatbot.WhatsappQr";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            phoneNumber: "",
            phoneId: null,
            status: "idle",         // idle | connecting | qr_ready | saving | connected | error
            statusMessage: "",
            qrImageSrc: "",
            whatsappId: "",
            errorDetail: "",
        });

        this.socket = null;
        this.connectionTimeout = null;

        onMounted(() => this._initialize());
        onWillUnmount(() => this._cleanup());
    }

    async _initialize() {
        const ctx = this.props.action?.context || {};
        this.state.phoneNumber = ctx.phone_number || "";
        this.state.phoneId = ctx.phone_id || null;

        if (!this.state.phoneNumber) {
            this.state.status = "error";
            this.state.statusMessage = "No se proporcionó número de teléfono.";
            return;
        }

        // Fetch the WebSocket URL from ir.config_parameter
        let wsUrl = await this.orm.call(
            "ir.config_parameter", "get_param",
            ["hospital_chatbot.whatsapp_login_url"],
        );
        if (!wsUrl) {
            wsUrl = await this.orm.call(
                "ir.config_parameter", "get_param",
                ["hospital_chatbot.whatsapp_service_url"],
            );
        }

        if (!wsUrl) {
            this.state.status = "error";
            this.state.statusMessage = "URL del servicio WhatsApp no configurada.";
            return;
        }

        this.wsUrl = wsUrl;
        this._startLogin();
    }

    _startLogin() {
        this.state.status = "connecting";
        this.state.statusMessage = "Conectando con el servicio WhatsApp...";
        this.state.qrImageSrc = "";
        this.state.errorDetail = "";
        this._connectWebSocket();
    }

    _connectWebSocket() {
        if (this.socket) {
            this.socket.disconnect();
            this.socket = null;
        }

        if (typeof io === "undefined") {
            this.state.status = "error";
            this.state.statusMessage = "Socket.IO no disponible. Recargue la página.";
            return;
        }

        try {
            this.socket = io(this.wsUrl, {
                transports: ["websocket", "polling"],
                reconnection: true,
                reconnectionAttempts: 5,
                reconnectionDelay: 1000,
            });

            this.socket.on("connect", () => {
                console.log("[WhatsApp QR] Socket connected, emitting login for:", this.state.phoneNumber);
                this.socket.emit("login", { phone: this.state.phoneNumber });
                this._startConnectionTimeout();
            });

            this.socket.on("login:status", (data) => {
                console.log("[WhatsApp QR] login:status", data);
                if (data.status === "initializing") {
                    this.state.statusMessage = "Inicializando conexión...";
                } else if (data.status === "reconnecting") {
                    this.state.statusMessage = `Reconectando (intento ${data.retry || "?"}/${data.maxRetries || "?"})...`;
                }
            });

            this.socket.on("login:qr", (data) => {
                console.log("[WhatsApp QR] login:qr received");
                this._clearConnectionTimeout();
                if (data.qr) {
                    this.state.status = "qr_ready";
                    this.state.qrImageSrc = data.qr;
                    this.state.statusMessage = "Escanee el código QR con WhatsApp";
                }
            });

            this.socket.on("login:connected", (data) => {
                console.log("[WhatsApp QR] login:connected", data);
                this._clearConnectionTimeout();
                this.state.whatsappId = data.whatsappId || data.whatsapp_id || data.id || "";
                this._onConnected();
            });

            this.socket.on("login:error", (data) => {
                console.log("[WhatsApp QR] login:error", data);
                this._clearConnectionTimeout();
                this.state.status = "error";
                this.state.statusMessage = "Error al conectar";
                this.state.errorDetail = data.error || "";
            });

            this.socket.on("login:logged_out", (data) => {
                console.log("[WhatsApp QR] login:logged_out", data);
                this.state.status = "error";
                this.state.statusMessage = "La sesión fue cerrada. Intente nuevamente.";
            });

            this.socket.on("login:disconnected", (data) => {
                console.log("[WhatsApp QR] login:disconnected", data);
                this.state.status = "error";
                this.state.statusMessage = `Desconectado: ${data.reason || "razón desconocida"}`;
            });

            this.socket.on("connect_error", (error) => {
                console.log("[WhatsApp QR] connect_error", error);
                this._clearConnectionTimeout();
                this.state.status = "error";
                this.state.statusMessage = "Error de conexión con el servicio.";
                this.state.errorDetail = "Verifique que el servicio WhatsApp esté ejecutándose.";
            });

            this.socket.on("disconnect", (reason) => {
                console.log("[WhatsApp QR] socket disconnected:", reason);
                if (reason === "io server disconnect" && this.state.status !== "connected" && this.state.status !== "saving") {
                    this.socket.connect();
                }
            });
        } catch (e) {
            console.error("[WhatsApp QR] WebSocket setup error:", e);
            this.state.status = "error";
            this.state.statusMessage = "No se pudo conectar al servicio WebSocket.";
        }
    }

    async _onConnected() {
        // Show success state in the modal
        this.state.status = "saving";
        this.state.statusMessage = "¡Conectado exitosamente! Guardando sesión...";

        // Clean up socket immediately — the loginqr server closes it anyway
        this._cleanup();

        if (!this.state.phoneId) {
            this.state.status = "connected";
            this.state.statusMessage = "¡Conectado exitosamente!";
            return;
        }

        try {
            // Call server-side method to save status + start chatbot listener
            await this.orm.call(
                "hospital.chatbot.whatsapp.phone",
                "action_save_qr_session",
                [[this.state.phoneId], this.state.whatsappId],
            );

            this.state.status = "connected";
            this.state.statusMessage = "¡Conectado exitosamente!";

            this.notification.add("Sesión de WhatsApp conectada y guardada", {
                type: "success",
            });

            // Wait briefly to show success, then reload the page
            setTimeout(() => {
                window.location.reload();
            }, SUCCESS_DISPLAY_MS);
        } catch (e) {
            console.error("[WhatsApp QR] save error:", e);
            this.state.status = "error";
            this.state.statusMessage = "Conectado, pero hubo un error al guardar.";
            this.state.errorDetail = e.message || String(e);
            this.notification.add("Error al guardar la sesión", {
                type: "danger",
            });
        }
    }

    onRetry() {
        this._startLogin();
    }

    onCancel() {
        if (this.socket && this.state.phoneNumber) {
            this.socket.emit("login:cancel", { phone: this.state.phoneNumber });
        }
        this._cleanup();
        this.action.doAction({ type: "ir.actions.act_window_close" });
    }

    _startConnectionTimeout() {
        this._clearConnectionTimeout();
        this.connectionTimeout = setTimeout(() => {
            if (this.state.status === "connecting") {
                this.state.status = "error";
                this.state.statusMessage = "Tiempo de espera agotado. Intente nuevamente.";
            }
        }, CONNECTION_TIMEOUT_MS);
    }

    _clearConnectionTimeout() {
        if (this.connectionTimeout) {
            clearTimeout(this.connectionTimeout);
            this.connectionTimeout = null;
        }
    }

    _cleanup() {
        this._clearConnectionTimeout();
        if (this.socket) {
            this.socket.disconnect();
            this.socket = null;
        }
    }
}

registry.category("actions").add("hospital_chatbot.whatsapp_qr", WhatsappQrAction);
