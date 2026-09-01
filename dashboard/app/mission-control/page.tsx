import { redirect } from "next/navigation";

export default function MissionControlPage() {
  redirect("/command-center?view=operations");
}
