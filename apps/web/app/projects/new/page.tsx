import Link from "next/link";

import { ProjectForm } from "@/components/project-form";

export default function NewProjectPage(): React.ReactElement {
  return (
    <main>
      <p className="breadcrumb">
        <Link href="/projects">← Projects</Link>
      </p>
      <h1>New project</h1>
      <p className="subtitle">
        A project is a study area plus the projected metric CRS every calculation for it uses.
      </p>
      <ProjectForm />
    </main>
  );
}
