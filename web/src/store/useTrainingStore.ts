import { create } from 'zustand';

interface TrainingParams {
  symbol: string;
  start_date: string;
  end_date: string;
  epochs: number;
  learning_rate: number;
  entropy_coef: number;
}

type JobStatus = 'IDLE' | 'PENDING' | 'PROGRESS' | 'SUCCESS' | 'FAILURE';

interface TrainingState {
  // Data
  params: TrainingParams;
  jobId: string | null;
  status: JobStatus;
  progress: number;
  logs: string[];
  
  // Actions
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
    entropy_coef: 0.01
  },
  jobId: null,
  status: 'IDLE',
  progress: 0,
  logs: [],

  setParams: (newParams) => set((state) => ({ params: { ...state.params, ...newParams } })),
  setJobId: (id) => set({ jobId: id }),
  setStatus: (status) => set({ status }),
  setProgress: (progress) => set({ progress }),
  
  // Automatically appends the timestamp to logs
  addLog: (msg) => set((state) => ({ 
    logs: [...state.logs, `[${new Date().toLocaleTimeString()}] ${msg}`] 
  })),
  
  resetJob: () => set({ jobId: null, status: 'IDLE', progress: 0, logs: [] })
}));