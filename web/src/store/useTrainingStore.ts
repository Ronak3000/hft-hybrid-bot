import { create } from 'zustand';

interface TrainingParams {
  symbol: string;
  start_date: string;
  end_date: string;
  epochs: number;
  learning_rate: number;
  entropy_coef: number;
  starting_cash: number;
  base_trade_size: number;
  max_inventory: number;
  maker_fee: number;
  penalty_factor: number;
  kappa: number;
}

type JobStatus = 'IDLE' | 'PENDING' | 'PROGRESS' | 'SUCCESS' | 'FAILURE';

interface TrainingState {
  params: TrainingParams;
  jobId: string | null;
  status: JobStatus;
  progress: number;
  logs: string[];
  
  setParams: (params: Partial<TrainingParams>) => void;
  setJobId: (id: string | null) => void;
  setStatus: (status: JobStatus) => void;
  setProgress: (progress: number) => void;
  addLog: (msg: string) => void;
  resetJob: () => void;
}

export const useTrainingStore = create<TrainingState>((set) => ({
  params: {
    symbol: 'BTC/USDT',
    start_date: '2023-01-01',
    end_date: '2023-01-30',
    epochs: 100,
    learning_rate: 0.0003,
    entropy_coef: 0.01,
    starting_cash: 1000000.0,
    base_trade_size: 0.5,
    max_inventory: 6.0,
    maker_fee: -0.0001,
    penalty_factor: 0.1,
    kappa: 1.5
  },
  jobId: null,
  status: 'IDLE',
  progress: 0,
  logs: [],

  // THIS IS THE CRITICAL LINE: It must merge the new params with the old ones
  setParams: (newParams) => set((state) => ({ params: { ...state.params, ...newParams } })),
  
  setJobId: (id) => set({ jobId: id }),
  setStatus: (status) => set({ status }),
  setProgress: (progress) => set({ progress }),
  addLog: (msg) => set((state) => ({ 
    logs: [...state.logs, `[${new Date().toLocaleTimeString()}] ${msg}`] 
  })),
  resetJob: () => set({ jobId: null, status: 'IDLE', progress: 0, logs: [] })
}));