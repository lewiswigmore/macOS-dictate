import { exec } from "node:child_process";
import { popToRoot, showHUD } from "@raycast/api";
import { showFailureToast } from "@raycast/utils";

export default async function main() {
  try {
    await new Promise<void>((resolve, reject) => {
      exec("open 'dictate://stop'", (err) => (err ? reject(err) : resolve()));
    });
    await showHUD("⏹ Stopped");
    await popToRoot();
  } catch (error) {
    await showFailureToast(error, { title: "Failed to stop recording" });
  }
}
