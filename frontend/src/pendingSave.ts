export type PendingSave = () => Promise<void>;
export type RegisterPendingSave = (save: PendingSave | null) => void;
