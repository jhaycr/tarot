// Light cleanup for LLM reading text. The prompts ask for plain prose, but as a
// safety net we strip stray markdown so headings/bold/list markers never render
// as literal characters, and split into paragraphs for readable rendering.

export function toParagraphs(text: string): string[] {
	return cleanReading(text)
		.split(/\n{2,}/)
		.map((p) => p.trim())
		.filter(Boolean);
}

export function cleanReading(text: string): string {
	return text
		.split('\n')
		.map((line) =>
			line
				.replace(/^\s{0,3}#{1,6}\s+/, '') // ## Heading -> Heading
				.replace(/^\s*[-*+]\s+/, '') // - bullet -> plain
				.replace(/^\s*\d+\.\s+/, '') // 1. item -> plain
		)
		.join('\n')
		.replace(/\*\*(.+?)\*\*/g, '$1') // **bold** -> bold
		.replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, '$1') // *italic* -> italic
		.replace(/`([^`]+)`/g, '$1'); // `code` -> code
}
