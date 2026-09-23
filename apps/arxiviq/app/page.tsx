import { redirect } from "next/navigation";

import SystemOneHome from "./components/SystemOneHome";
import { META_DESCRIPTION, META_TITLE } from "../lib/system-one-copy";

export const metadata = {
  title: META_TITLE,
  description: META_DESCRIPTION,
};

export default async function Home({
  searchParams,
}: {
  searchParams?: Promise<{ tandem?: string }>;
}) {
  const params = await searchParams;
  if (params?.tandem === "1" || params?.tandem === "true") {
    redirect("/conductor?tandem=1");
  }
  return <SystemOneHome />;
}
