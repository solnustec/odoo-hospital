/** @odoo-module */

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, useRef, onMounted, onWillUnmount } from "@odoo/owl";

const NODE_COLORS = {
    MESSAGE: "#3498db",
    MENU: "#2ecc71",
    QUESTION: "#f39c12",
    CONDITION: "#e67e22",
    FILE: "#9b59b6",
    API_CALL: "#1abc9c",
    TRANSFER_AGENT: "#e74c3c",
    DELAY: "#95a5a6",
    SET_VARIABLE: "#34495e",
    GO_TO_FLOW: "#2980b9",
    AI_AGENT: "#8e44ad",
};

const NODE_ICONS = {
    MESSAGE: "fa-comment",
    MENU: "fa-list",
    QUESTION: "fa-question-circle",
    CONDITION: "fa-code-fork",
    FILE: "fa-file",
    API_CALL: "fa-plug",
    TRANSFER_AGENT: "fa-user",
    DELAY: "fa-clock-o",
    SET_VARIABLE: "fa-database",
    GO_TO_FLOW: "fa-share",
    AI_AGENT: "fa-robot",
};

const NODE_WIDTH = 180;
const NODE_HEIGHT = 60;

class FlowBuilderWidget extends Component {
    static template = "hospital_chatbot.FlowBuilder";
    static props = {
        record: { type: Object },
        readonly: { type: Boolean, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.canvasRef = useRef("canvas");

        this.state = useState({
            nodes: [],
            connections: [],
            dragging: null,
            connecting: null,
            pan: { x: 0, y: 0 },
            isPanning: false,
            panStart: { x: 0, y: 0 },
            selectedNode: null,
            contextMenu: null,
            zoom: 1,
        });

        onMounted(() => this.loadData());
        onWillUnmount(() => this._cleanup());
    }

    async loadData() {
        const flowId = this.props.record.resId;
        if (!flowId) return;

        const nodes = await this.orm.searchRead(
            "hospital.chatbot.node",
            [["flow_id", "=", flowId]],
            ["id", "name", "node_type", "position_x", "position_y", "is_start", "order"],
        );

        const connections = await this.orm.searchRead(
            "hospital.chatbot.node.connection",
            [["from_node_id", "in", nodes.map((n) => n.id)]],
            ["id", "from_node_id", "to_node_id", "label", "option_value", "condition"],
        );

        // Default positions for nodes without positions
        let offsetX = 50;
        let offsetY = 50;
        for (const node of nodes) {
            if (node.position_x === 0 && node.position_y === 0) {
                node.position_x = offsetX;
                node.position_y = offsetY;
                offsetY += NODE_HEIGHT + 30;
                if (offsetY > 500) {
                    offsetY = 50;
                    offsetX += NODE_WIDTH + 80;
                }
            }
        }

        this.state.nodes = nodes;
        this.state.connections = connections;
    }

    // =========================================================================
    // Node dragging
    // =========================================================================

    onNodeMouseDown(ev, node) {
        if (ev.button !== 0) return;
        ev.stopPropagation();
        this.state.selectedNode = node.id;
        this.state.dragging = {
            nodeId: node.id,
            startX: ev.clientX,
            startY: ev.clientY,
            origX: node.position_x,
            origY: node.position_y,
        };
        this._onMouseMoveBound = this.onMouseMove.bind(this);
        this._onMouseUpBound = this.onMouseUp.bind(this);
        document.addEventListener("mousemove", this._onMouseMoveBound);
        document.addEventListener("mouseup", this._onMouseUpBound);
    }

    onMouseMove(ev) {
        if (this.state.dragging) {
            const d = this.state.dragging;
            const dx = (ev.clientX - d.startX) / this.state.zoom;
            const dy = (ev.clientY - d.startY) / this.state.zoom;
            const node = this.state.nodes.find((n) => n.id === d.nodeId);
            if (node) {
                node.position_x = Math.max(0, d.origX + dx);
                node.position_y = Math.max(0, d.origY + dy);
            }
        } else if (this.state.isPanning) {
            const dx = ev.clientX - this.state.panStart.x;
            const dy = ev.clientY - this.state.panStart.y;
            this.state.pan.x += dx;
            this.state.pan.y += dy;
            this.state.panStart.x = ev.clientX;
            this.state.panStart.y = ev.clientY;
        }
    }

    async onMouseUp(ev) {
        if (this.state.dragging) {
            const node = this.state.nodes.find((n) => n.id === this.state.dragging.nodeId);
            if (node) {
                await this.orm.write("hospital.chatbot.node", [node.id], {
                    position_x: node.position_x,
                    position_y: node.position_y,
                });
            }
            this.state.dragging = null;
        }
        this.state.isPanning = false;
        document.removeEventListener("mousemove", this._onMouseMoveBound);
        document.removeEventListener("mouseup", this._onMouseUpBound);
    }

    // =========================================================================
    // Canvas panning & zoom
    // =========================================================================

    onCanvasMouseDown(ev) {
        if (ev.button !== 0) return;
        if (ev.target === this.canvasRef.el || ev.target.tagName === "svg") {
            this.state.isPanning = true;
            this.state.panStart = { x: ev.clientX, y: ev.clientY };
            this.state.selectedNode = null;
            this.state.contextMenu = null;
            this._onMouseMoveBound = this.onMouseMove.bind(this);
            this._onMouseUpBound = this.onMouseUp.bind(this);
            document.addEventListener("mousemove", this._onMouseMoveBound);
            document.addEventListener("mouseup", this._onMouseUpBound);
        }
    }

    onWheel(ev) {
        ev.preventDefault();
        const delta = ev.deltaY > 0 ? -0.1 : 0.1;
        this.state.zoom = Math.max(0.3, Math.min(2, this.state.zoom + delta));
    }

    // =========================================================================
    // Connection drawing
    // =========================================================================

    onPortMouseDown(ev, node, portType) {
        ev.stopPropagation();
        if (portType === "output") {
            this.state.connecting = { fromId: node.id };
        }
    }

    async onPortMouseUp(ev, node, portType) {
        ev.stopPropagation();
        if (this.state.connecting && portType === "input" && this.state.connecting.fromId !== node.id) {
            // Create connection
            const fromId = this.state.connecting.fromId;
            try {
                const connId = await this.orm.create("hospital.chatbot.node.connection", [{
                    from_node_id: fromId,
                    to_node_id: node.id,
                    label: "",
                    condition: "",
                    option_value: "",
                }]);
                this.state.connections.push({
                    id: connId[0],
                    from_node_id: [fromId],
                    to_node_id: [node.id],
                    label: "",
                    option_value: "",
                    condition: "",
                });
            } catch (e) {
                console.warn("Connection already exists or invalid", e);
            }
        }
        this.state.connecting = null;
    }

    // =========================================================================
    // Context menu & actions
    // =========================================================================

    onContextMenu(ev) {
        ev.preventDefault();
        const rect = this.canvasRef.el.getBoundingClientRect();
        this.state.contextMenu = {
            x: ev.clientX - rect.left,
            y: ev.clientY - rect.top,
            canvasX: (ev.clientX - rect.left - this.state.pan.x) / this.state.zoom,
            canvasY: (ev.clientY - rect.top - this.state.pan.y) / this.state.zoom,
            nodeId: null,
        };
    }

    onNodeContextMenu(ev, node) {
        ev.preventDefault();
        ev.stopPropagation();
        const rect = this.canvasRef.el.getBoundingClientRect();
        this.state.contextMenu = {
            x: ev.clientX - rect.left,
            y: ev.clientY - rect.top,
            nodeId: node.id,
        };
    }

    async addNode(nodeType) {
        const menu = this.state.contextMenu;
        const flowId = this.props.record.resId;
        const ids = await this.orm.create("hospital.chatbot.node", [{
            flow_id: flowId,
            node_type: nodeType,
            name: `Nuevo ${nodeType.toLowerCase()}`,
            position_x: menu.canvasX || 100,
            position_y: menu.canvasY || 100,
            is_start: this.state.nodes.length === 0,
            config: {},
        }]);
        this.state.contextMenu = null;
        await this.loadData();
    }

    async deleteNode(nodeId) {
        await this.orm.unlink("hospital.chatbot.node", [nodeId]);
        this.state.contextMenu = null;
        await this.loadData();
    }

    async deleteConnection(connId) {
        await this.orm.unlink("hospital.chatbot.node.connection", [connId]);
        this.state.connections = this.state.connections.filter((c) => c.id !== connId);
    }

    async addNodeFromPalette(nodeType) {
        const flowId = this.props.record.resId;
        const y = this.state.nodes.length * (NODE_HEIGHT + 30) + 50;
        const ids = await this.orm.create("hospital.chatbot.node", [{
            flow_id: flowId,
            node_type: nodeType,
            name: `Nuevo ${nodeType.toLowerCase()}`,
            position_x: 250,
            position_y: y,
            is_start: this.state.nodes.length === 0,
            config: {},
        }]);
        await this.loadData();
    }

    openNodeForm(nodeId) {
        this.state.contextMenu = null;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "hospital.chatbot.node",
            res_id: nodeId,
            views: [[false, "form"]],
            target: "new",
        });
    }

    onNodeDblClick(ev, node) {
        ev.stopPropagation();
        this.openNodeForm(node.id);
    }

    // =========================================================================
    // SVG path helpers
    // =========================================================================

    getConnectionPath(conn) {
        const fromNode = this.state.nodes.find((n) => n.id === (conn.from_node_id[0] || conn.from_node_id));
        const toNode = this.state.nodes.find((n) => n.id === (conn.to_node_id[0] || conn.to_node_id));
        if (!fromNode || !toNode) return "";

        const x1 = fromNode.position_x + NODE_WIDTH;
        const y1 = fromNode.position_y + NODE_HEIGHT / 2;
        const x2 = toNode.position_x;
        const y2 = toNode.position_y + NODE_HEIGHT / 2;
        const cx = (x1 + x2) / 2;

        return `M ${x1} ${y1} C ${cx} ${y1}, ${cx} ${y2}, ${x2} ${y2}`;
    }

    getConnectionMidpoint(conn) {
        const fromNode = this.state.nodes.find((n) => n.id === (conn.from_node_id[0] || conn.from_node_id));
        const toNode = this.state.nodes.find((n) => n.id === (conn.to_node_id[0] || conn.to_node_id));
        if (!fromNode || !toNode) return { x: 0, y: 0 };
        return {
            x: (fromNode.position_x + NODE_WIDTH + toNode.position_x) / 2,
            y: (fromNode.position_y + toNode.position_y + NODE_HEIGHT) / 2,
        };
    }

    // =========================================================================
    // Helpers
    // =========================================================================

    getNodeColor(nodeType) {
        return NODE_COLORS[nodeType] || "#95a5a6";
    }

    getNodeIcon(nodeType) {
        return NODE_ICONS[nodeType] || "fa-circle";
    }

    getNodeTypes() {
        return Object.keys(NODE_COLORS);
    }

    getTransform() {
        return `translate(${this.state.pan.x}px, ${this.state.pan.y}px) scale(${this.state.zoom})`;
    }

    _cleanup() {
        if (this._onMouseMoveBound) {
            document.removeEventListener("mousemove", this._onMouseMoveBound);
        }
        if (this._onMouseUpBound) {
            document.removeEventListener("mouseup", this._onMouseUpBound);
        }
    }
}

// Register as a form view widget
registry.category("view_widgets").add("flow_builder", {
    component: FlowBuilderWidget,
});
