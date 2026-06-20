// =============================================================================
// ChangePasswordDialog — modal for the logged-in user to rotate their own
// password.
//
// Exposes two things:
//   - <ChangePasswordDialog open onOpenChange /> the modal itself
//   - <ChangePasswordDialogTrigger /> a DropdownMenuItem that opens it
//
// The trigger is split so it slots into the existing user-menu dropdown in
// Layout.js without forcing the parent to manage open-state.
// =============================================================================

import React, { useState } from "react";
import { Key } from "lucide-react";
import { toast } from "sonner";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../ui/dialog";
import { DropdownMenuItem } from "../ui/dropdown-menu";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { changePassword } from "../../api/auth";
import { authMessage } from "../../lib/utils";

export const ChangePasswordDialog = ({ open, onOpenChange }) => {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const reset = () => {
    setCurrentPassword("");
    setNewPassword("");
    setConfirm("");
    setSubmitting(false);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (newPassword.length < 8) {
      toast.error("New password must be at least 8 characters");
      return;
    }
    if (newPassword !== confirm) {
      toast.error("Passwords do not match");
      return;
    }
    setSubmitting(true);
    try {
      await changePassword(currentPassword, newPassword);
      toast.success("Password changed");
      reset();
      onOpenChange(false);
    } catch (err) {
      toast.error(authMessage(err, "Couldn't change your password."));
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) reset();
        onOpenChange(v);
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Key className="h-4 w-4" />
            Change password
          </DialogTitle>
          <DialogDescription>
            Enter your current password and choose a new one. You will stay
            signed in on this device.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <Label className="text-xs">Current password</Label>
            <Input
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </div>
          <div>
            <Label className="text-xs">New password</Label>
            <Input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              autoComplete="new-password"
              minLength={8}
              required
            />
            <p className="text-[11px] text-muted-foreground mt-1">
              Use at least 8 characters. Your administrator may require a mix of
              upper-case letters, numbers, or symbols.
            </p>
          </div>
          <div>
            <Label className="text-xs">Confirm new password</Label>
            <Input
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              autoComplete="new-password"
              minLength={8}
              required
            />
          </div>

          <DialogFooter className="pt-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
              disabled={submitting}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? "Changing…" : "Change password"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

// Slots into the user-menu DropdownMenuContent in Layout.js.
// Owns its own open-state so the parent menu only needs to render <ChangePasswordDialogTrigger />.
export const ChangePasswordDialogTrigger = () => {
  const [open, setOpen] = useState(false);
  return (
    <>
      <DropdownMenuItem
        onSelect={(e) => {
          // prevent the dropdown from auto-closing before the dialog mounts
          e.preventDefault();
          setOpen(true);
        }}
        className="focus:bg-card/70 focus:text-white"
      >
        <Key className="h-4 w-4 mr-2" />
        Change password
      </DropdownMenuItem>
      <ChangePasswordDialog open={open} onOpenChange={setOpen} />
    </>
  );
};

export default ChangePasswordDialog;
