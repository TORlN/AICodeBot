from aicodebot.coder import Coder
from aicodebot.helpers import logger
from aicodebot.lm import DEFAULT_RESPONSE_TOKENS, LanguageModelManager, get_token_size
from aicodebot.output import OurMarkdown, RichLiveCallbackHandler, get_console
from aicodebot.prompts import get_prompt
from langchain.chains import LLMChain
from rich.live import Live
import click, json, sys


@click.command
@click.option("-c", "--commit", help="The commit hash to review (otherwise look at [un]staged changes).")
@click.option("--output-format", default="text", type=click.Choice(["text", "json"], case_sensitive=False))
@click.option("-t", "--response-token-size", type=int, default=DEFAULT_RESPONSE_TOKENS * 2)
@click.argument("files", nargs=-1)
def review(commit, output_format, response_token_size, files):
    """Do a code review, with [un]staged changes, or a specified commit."""
    console = get_console()
    if not Coder.is_inside_git_repo():
        console.print("🛑 This command must be run from within a git repository.", style=console.error_style)
        sys.exit(1)

    # If files are specified, only consider those files
    # Otherwise, use git to get the list of files
    if not files:
        files = Coder.git_staged_files()
        if not files:
            files = Coder.git_unstaged_files()

    diff_context = Coder.git_diff_context(commit, files)
    if not diff_context:
        console.print("No changes detected for review. 🤷")
        return
    languages = ",".join(Coder.identify_languages(files))

    # Load the prompt
    prompt = get_prompt("review", structured_output=output_format == "json")
    logger.trace(f"Prompt: {prompt}")

    # Check the size of the diff context and adjust accordingly
    request_token_size = get_token_size(diff_context) + get_token_size(prompt.template)
    lmm = LanguageModelManager()
    model_name = lmm.choose_model(request_token_size + response_token_size)
    if model_name is None:
        raise click.ClickException(f"The diff is too large to review ({request_token_size} tokens). 😢")

    llm = lmm.get_langchain_model(model_name, streaming=True)
    chain = lmm.get_langchain_chain(llm=llm, prompt=prompt)

    if output_format == "json":
        with console.status("Examining the diff and generating the review", spinner=console.DEFAULT_SPINNER):
            response = chain.run({"diff_context": diff_context, "languages": languages})

        parsed_response = prompt.output_parser.parse(response)
        data = {
            "review_status": parsed_response.review_status,
            "review_comments": parsed_response.review_comments,
        }
        if commit:
            data["commit"] = commit
        json_response = json.dumps(data, indent=4)
        print(json_response)  # noqa: T201

    else:
        # Stream live
        console.print(
            "Examining the diff and generating the review for the following files:\n\t" + "\n\t".join(files)
        )
        with Live(OurMarkdown(""), auto_refresh=True) as live:
            llm.streaming = True
            llm.callbacks = [RichLiveCallbackHandler(live, console.bot_style)]

            chain.run({"diff_context": diff_context, "languages": languages})