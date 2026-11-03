import { defineConfig } from "react-doctor/api";

export default defineConfig({
  ignore: {
    overrides: [
      // shadcn/ui components export their cva variants next to the component by design.
      { files: ["src/shared/ui/**"], rules: ["react-doctor/only-export-components"] },
    ],
  },
});
