// openapi-typescript drives the TypeScript compiler API, which TypeScript 7 (native) does not
// ship. Give it its own TypeScript 5 instead of the app's, so `pnpm gen:api` is locked in
// pnpm-lock.yaml. Drop this once openapi-typescript supports TypeScript 7.
module.exports = {
  hooks: {
    readPackage(pkg) {
      if (pkg.name === "openapi-typescript") {
        delete pkg.peerDependencies.typescript;
        pkg.dependencies = { ...pkg.dependencies, typescript: "npm:typescript@5.9.3" };
      }
      return pkg;
    },
  },
};
