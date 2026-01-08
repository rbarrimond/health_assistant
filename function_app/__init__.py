"""Azure Functions app entry point."""
import azure.functions as func
from function_app.function_handler import main

app = func.FunctionApp()

@app.function_name("ProcessFitFiles")
@app.route(route="process_fit", methods=["POST"])
def process_fit_files(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP-triggered function to process FIT files from OneDrive."""
    return main(req)
