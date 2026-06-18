// =============================================================================
// useConfirm — imperative, consistent confirm dialog (replaces window.confirm).
//
//   const confirm = useConfirm();
//   if (await confirm({ title: "Delete event?", confirmText: "Delete", danger: true }))
//     doDelete();
//
// Wrap the app (or a subtree) in <ConfirmProvider>. Renders the shadcn
// AlertDialog so confirmations match the rest of the UI instead of the browser's
// native dialog.
// =============================================================================
import React, { createContext, useCallback, useContext, useRef, useState } from "react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "./alert-dialog";

const ConfirmContext = createContext(null);

const DEFAULTS = {
  title: "Are you sure?",
  description: "",
  confirmText: "Confirm",
  cancelText: "Cancel",
  danger: false,
};

export function ConfirmProvider({ children }) {
  const [open, setOpen] = useState(false);
  const [opts, setOpts] = useState(DEFAULTS);
  const resolver = useRef(null);

  const confirm = useCallback((options = {}) => {
    setOpts({ ...DEFAULTS, ...options });
    setOpen(true);
    return new Promise((resolve) => { resolver.current = resolve; });
  }, []);

  const settle = (val) => {
    setOpen(false);
    resolver.current?.(val);
    resolver.current = null;
  };

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <AlertDialog open={open} onOpenChange={(o) => { if (!o) settle(false); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{opts.title}</AlertDialogTitle>
            {opts.description && (
              <AlertDialogDescription>{opts.description}</AlertDialogDescription>
            )}
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => settle(false)}>{opts.cancelText}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => settle(true)}
              className={opts.danger ? "bg-rose-600 hover:bg-rose-500 text-white" : undefined}
            >
              {opts.confirmText}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </ConfirmContext.Provider>
  );
}

export function useConfirm() {
  const ctx = useContext(ConfirmContext);
  if (!ctx) {
    // Fallback if provider missing — keeps callers safe (shouldn't happen).
    return async (o = {}) => window.confirm(o.title || "Are you sure?");
  }
  return ctx;
}
