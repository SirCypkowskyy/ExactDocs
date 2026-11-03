export interface Library {
  readonly name: string;
  readonly versions: readonly string[];
}

export interface LibrariesResponse {
  readonly libraries: readonly Library[];
}
