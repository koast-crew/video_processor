import tensorrt as trt, torch, ultralytics, sys
print("Python     :", sys.version.split()[0])      # 3.12.x
print("Torch      :", torch.__version__)
print("TensorRT   :", trt.__version__)             # 10.0.1
print("CUDA avail :", torch.cuda.is_available())   # True
print("Ultralytics:", ultralytics.__version__)