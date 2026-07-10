import { create } from 'zustand';

interface Execution {
  time: string;
  side: string;
  price: number;
  size: number;
  realized_pnl: number;
}

interface TradingState {
  midPrice: number;
  netWorth: number;
  inventory: number;
  executions: Execution[];
  isConnected: boolean;
  connect: () => void;
  disconnect: () => void;
}

let ws: WebSocket | null = null;

export const useTradingStore = create<TradingState>((set) => ({
  midPrice: 62500,
  netWorth: 10000,
  inventory: 0,
  executions: [],
  isConnected: false,

  connect: () => {
    if (ws) return;
    ws = new WebSocket('ws://localhost:8000/ws/live');

    ws.onopen = () => set({ isConnected: true });
    
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      set((state) => ({
        midPrice: data.mid_price,
        netWorth: data.net_worth,
        inventory: data.inventory_btc,
        // Keep only the last 50 executions in memory to prevent DOM bloat
        executions: [...data.latest_executions, ...state.executions].slice(0, 50)
      }));
    };

    ws.onclose = () => {
      set({ isConnected: false });
      ws = null;
    };
  },

  disconnect: () => {
    if (ws) {
      ws.close();
      ws = null;
    }
  }
}));