import { PipelineProgress } from './PipelineProgress';

export default {
  title: 'Kadode/PipelineProgress',
  component: PipelineProgress,
};

export const NotStarted = { args: { currentStage: null } };
export const StageZero = { args: { currentStage: 0 } };
export const DeepDive = { args: { currentStage: 2 } };
