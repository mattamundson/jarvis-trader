import { redirect } from "next/navigation";

// Client-free redirect for /dashboard -> /command-center.
// Using server-only redirect() here can fail this route in some build modes,
// so this component performs the navigation client-side.
export default function DashboardPage() {
  redirect("/command-center");
}
