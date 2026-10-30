"""Internal unittest reporter, launched only by the explicit collector CLI."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import unittest


class Result(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.cases=[]
    def record(self,test,status):self.cases.append({'test_id':test.id(),'status':status})
    def addSuccess(self,test):super().addSuccess(test);self.record(test,'passed')
    def addFailure(self,test,err):super().addFailure(test,err);self.record(test,'failed')
    def addError(self,test,err):super().addError(test,err);self.record(test,'error')
    def addSkip(self,test,reason):super().addSkip(test,reason);self.record(test,'skipped')
    def addExpectedFailure(self,test,err):super().addExpectedFailure(test,err);self.record(test,'skipped')
    def addUnexpectedSuccess(self,test):super().addUnexpectedSuccess(test);self.record(test,'failed')
    def addSubTest(self,test,subtest,err):
        super().addSubTest(test,subtest,err)
        if err is not None:self.record(test,'failed' if issubclass(err[0],test.failureException) else 'error')


def main():
    parser=argparse.ArgumentParser()
    for name in ('test-file','report','execution-id','nonce'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    path=Path(args.test_file).resolve(strict=True)
    sys.path.insert(0,str(Path.cwd()));sys.path.insert(0,str(path.parent))
    try:
        spec=importlib.util.spec_from_file_location('buildchoice_tests',path)
        module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
        suite=unittest.defaultTestLoader.loadTestsFromModule(module)
        result=unittest.TextTestRunner(stream=sys.stderr,resultclass=Result,verbosity=2).run(suite)
        report={'execution_id':args.execution_id,'nonce':args.nonce,'cases':result.cases,'tests_run':result.testsRun}
        code=0 if result.wasSuccessful() else 1
    except BaseException as exc:
        report={'execution_id':args.execution_id,'nonce':args.nonce,'cases':[],'tests_run':0,'worker_error':type(exc).__name__}
        code=2
    Path(args.report).write_text(json.dumps(report,ensure_ascii=False),encoding='utf-8')
    return code


if __name__=='__main__':sys.exit(main())
