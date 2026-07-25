(() => {
  'use strict';
  const actionIds = [
    'refreshButton','chooseButton','clearButton','applyEnhance','applyReconstruct','applyExtractPrint',
    'applySelection','applyCleanup','applyHalftone','applyVectorize','applyGeometry','applyExport',
    'runQaButton','runReportButton','aiAnalyzeSelected','aiExplainSelected','aiAccept','aiReject',
    'aiTrainButton','aiRollbackButton'
  ];
  const assetActionIds = [
    'applyEnhance','applyReconstruct','applyExtractPrint','applySelection','applyCleanup','applyHalftone',
    'applyVectorize','applyGeometry','applyExport','runQaButton','runReportButton','aiAnalyzeSelected',
    'aiExplainSelected','aiAccept','aiReject'
  ];
  const repair = document.getElementById('globalAutoRepair');
  const mode = document.getElementById('globalOperationMode');
  state.autoRepairPreference = repair ? repair.checked : true;

  function syncOperationModeControlsM1() {
    if (!repair) return;
    const forcedOff = state.operationMode === 'fast' || state.operationMode === 'check-only';
    repair.disabled = forcedOff || state.busy;
    repair.checked = forcedOff ? false : Boolean(state.autoRepairPreference);
    repair.setAttribute('aria-disabled', repair.disabled ? 'true' : 'false');
  }

  effectiveAutoRepair = function effectiveAutoRepairM1() {
    if (state.operationMode === 'fast' || state.operationMode === 'check-only') return false;
    return repair ? repair.checked : Boolean(state.autoRepairPreference);
  };

  const baseSyncLocks = syncLocks;
  syncLocks = function syncLocksM1() {
    baseSyncLocks();
    const hasAsset = Boolean(selectedAsset());
    const hasAssets = Boolean(state.project?.assets?.length);
    if (state.busy) {
      actionIds.forEach((id) => {
        const node = document.getElementById(id);
        if (node) node.disabled = true;
      });
    } else {
      assetActionIds.forEach((id) => {
        const node = document.getElementById(id);
        if (node) node.disabled = !hasAsset;
      });
      const choose = document.getElementById('chooseButton');
      const refresh = document.getElementById('refreshButton');
      const clear = document.getElementById('clearButton');
      if (choose) choose.disabled = false;
      if (refresh) refresh.disabled = false;
      if (clear) clear.disabled = !hasAssets;
    }
    syncOperationModeControlsM1();
  };

  const baseSetBusy = setBusy;
  setBusy = function setBusyM1(flag) {
    baseSetBusy(flag);
    syncLocks();
  };

  mode?.addEventListener('change', () => {
    syncOperationModeControlsM1();
    syncLocks();
  });
  repair?.addEventListener('change', () => {
    if (!repair.disabled) state.autoRepairPreference = repair.checked;
  });
  syncOperationModeControlsM1();
  syncLocks();
})();
