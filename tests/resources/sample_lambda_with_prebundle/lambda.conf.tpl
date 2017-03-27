lambda {
    handlerFunction = "handler.handle"
    handlerFile = "handler.py"
    description = "Test lambda with prebundle"
    timeout = 300
    memorySize = 128
}
bundling {
    preBundle = ["%s", "%s", "%s"]
    folders = [{ source = "./vendored", target = "." }]
}
