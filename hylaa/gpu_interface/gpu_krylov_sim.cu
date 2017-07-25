// Dung Tran
// An interface
// Krylov subspace - based simulation using Gpu- Cusp / Cuda for sparse ode
// June 2017

#include <new>
#include <stdio.h>
#include <stdlib.h>
#include <cusp/coo_matrix.h>
#include <cusp/csr_matrix.h>
#include <cusp/hyb_matrix.h>
#include <cusp/multiply.h>
#include <cusp/print.h>
#include <cusp/blas.h>
#include <sys/time.h>

typedef double FLOAT_TYPE;
typedef cusp::host_memory MEMORY_TYPE;
//typedef cusp::device_memory MEMORY_TYPE;

//static int choose_GPU = 0; // choose_GPU == 1 means that user choose to use GPU, if not, using CPU
// shared matrix in device memory
static cusp::hyb_matrix<int, FLOAT_TYPE, MEMORY_TYPE>* curMatrix = 0;
static std::vector< cusp::array1d<FLOAT_TYPE,MEMORY_TYPE> > V_;
static std::vector< cusp::array2d<FLOAT_TYPE,MEMORY_TYPE> > V_all; // use to compute n- Vm matrix
static std::vector< cusp::array2d<FLOAT_TYPE,MEMORY_TYPE> > V_all_final; // contain all n- Vm matrix
static std::vector< cusp::array2d<FLOAT_TYPE,MEMORY_TYPE> > H_all; // contain all n Hm matrix
static std::vector< cusp::array2d<FLOAT_TYPE,MEMORY_TYPE> > expHt_all; // contain all n exp(H*t) matrix, used to compute simulation result


static std::vector< cusp::array1d<FLOAT_TYPE, MEMORY_TYPE> > device_sim_result;
static cusp::hyb_matrix<int, FLOAT_TYPE, MEMORY_TYPE>* keyDirMatrix = 0;
static int numStepOfSim = 0;
static int systemSize = 0;
static int keyDirMatrix_w = 0;
static int keyDirMatrix_h = 0;

// timing shared variable
static long lastTicUs = 0;


void _choose_GPU_or_CPU(char* msg)
{
    if (strcmp(msg, "CPU")){
            printf("User choosed to use CPU \n");
            // choose_GPU = 0;
        }
        else if(strcmp(msg,"GPU")){
            printf("User choosed to use GPU \n");
            // choose_GPU = 1;
        }  else{
            printf("wrong input options, choose CPU or GPU only \n");
        }

}
 


void error(const char* msg)
{
    printf("Fatal Error: %s\n", msg);
    exit(1);             
}

void tic()
{
    struct timeval now;
    
    if(gettimeofday( &now, 0))
        error("gettimeofday");
        
    lastTicUs = 1000000 * now.tv_sec + now.tv_usec;
}

// returns the us elaspsed
long toc(const char* label)
{
    struct timeval now;
    
    if(gettimeofday( &now, 0))
        error("gettimeofday");
        
    long nowUs = 1000000 * now.tv_sec + now.tv_usec;
    long dif = nowUs - lastTicUs;
    
    printf("%s: %.4f ms\n", label, dif / 1000.0);
    
    return dif;
}

void _loadMatrix(int w, int h, int* nonZeroRows, int* nonZeroCols, double* nonZeroEntries, int nonZeroCount)
{
    tic();
    cusp::coo_matrix<int, FLOAT_TYPE, cusp::host_memory> hostMatrix(w, h, nonZeroCount);
        
    printf("loadMatrix() called, estimated size in memory of sparse matrix: %.2f MB (%d nonzeros)\n", 
        nonZeroCount * (8 + 4 + 4) / 1024.0 / 1024.0, nonZeroCount);

    // initialize matrix entries on host
    int index = 0;
 
    for (int i = 0; i < nonZeroCount; ++i)
    {
        int row = nonZeroRows[i];
        int col = nonZeroCols[i];
        double val = nonZeroEntries[i];
        
        hostMatrix.row_indices[index] = row;
        hostMatrix.column_indices[index] = col;
        hostMatrix.values[index++] = val;
    }
    
    toc("creating host coo matrix");
    
    tic();
    if (curMatrix != 0)
    {
        delete curMatrix;
        curMatrix = 0;
    }
    
    curMatrix = new (std::nothrow) cusp::hyb_matrix<int, FLOAT_TYPE,MEMORY_TYPE>(hostMatrix);
        
    if (curMatrix == 0)
        error("allocation of heap-based csr matrix in device memory returned nullptr");
        
    toc("copying matrix to device memory");
}

void _loadKeyDirMatrix(int w, int h, int* nonZeroRows, int* nonZeroCols, double* nonZeroEntries, int nonZeroCount)
{   // Load key Direction Sparse Matrix to get a particular direction of simulation result
    
    tic();
    keyDirMatrix_w = w;
    keyDirMatrix_h = h;
    
    cusp::coo_matrix<int, FLOAT_TYPE, cusp::host_memory> hostKeyMatrix(w, h, nonZeroCount);
        
    printf("loadKeyDirMatrix() called, estimated size in memory of sparse matrix: %.2f MB (%d nonzeros)\n", 
        nonZeroCount * (8 + 4 + 4) / 1024.0 / 1024.0, nonZeroCount);

    // initialize key matrix entries on host
    int index = 0;
 
    for (int i = 0; i < nonZeroCount; ++i)
    {
        int row = nonZeroRows[i];
        int col = nonZeroCols[i];
        double val = nonZeroEntries[i];
        
        hostKeyMatrix.row_indices[index] = row;
        hostKeyMatrix.column_indices[index] = col;
        hostKeyMatrix.values[index++] = val;
    }
    
    toc("creating host coo key matrix");
    
    tic();
    if (keyDirMatrix != 0)
    {
        delete keyDirMatrix;
        keyDirMatrix = 0;
    }
    
    keyDirMatrix = new (std::nothrow) cusp::hyb_matrix<int, FLOAT_TYPE,MEMORY_TYPE>(hostKeyMatrix);
        
    if (keyDirMatrix == 0)
        error("allocation of heap-based csr key matrix in device memory returned nullptr");
        
    toc("copying key matrix to device memory");

}

int _arnoldi_initVector(double* init_vector, double* result_H, int size, int numIter)
{
    
    if (curMatrix == 0)
        error("loadMatrix must be called before running arnoldi algorithm");
    
    // initialize input vector
    tic();
    cusp::array1d<FLOAT_TYPE, cusp::host_memory> hostInitVec(size);
    
    for (int i = 0; i < size; ++i)
        hostInitVec[i] = init_vector[i];
    toc("creating hostVec initial vector");
    
    // copy initial vector to device memory
    tic();
    cusp::array1d<FLOAT_TYPE,MEMORY_TYPE> deviceInitVec(hostInitVec);
    toc("copying initial vetocctor to device memory");

    // system dimension 
    tic();
    int N = size;
    toc("get system dimension");

    // maximum number of Iteration of Arnoldi algorithm
    tic();
    int maxiter = std::min(N, numIter);
    toc("get maximum number of iteration of arnoldi algorithm");

    // create matrix H_ in device memory for iteration
    tic();	
    cusp::array2d<FLOAT_TYPE,MEMORY_TYPE> H_(maxiter + 1, maxiter, 0);
    toc("create matrix H_ in device memory for iteration");

    // returned matrix H after iteration -- Hm in the algorithm -- (m x m) matrix 
    tic();
    cusp::array2d<FLOAT_TYPE,MEMORY_TYPE> H(maxiter, maxiter); 
    toc("create returned matrix H after iteration -- Hm in the algorithm -- (m x m) matrix ");

    // create matrix V_ for iteration
    tic();
    V_.resize(maxiter+1);
    for (int i = 0; i < maxiter + 1; i++)
        V_[i].resize(N);
    toc("create matrix V_ for iteration");

    // copy initial vector into V_[0]
    tic(); 
    cusp::copy(deviceInitVec,V_[0]); 
    toc("copy initial vector into V_[0]"); 

    // compute beta 
    tic();
    FLOAT_TYPE beta = cusp::blas::nrm2(deviceInitVec);
    toc("compute beta");
   

    // normalize initial vector
    cusp::blas::scal(V_[0], float(1)/beta);

    // iteration
    tic();
    int j;
    for(j = 0; j < maxiter; j++)
    {
	cusp::multiply(*curMatrix, V_[j], V_[j + 1]);
	
	for(int i = 0; i <= j; i++)
	{
		H_(i,j) = cusp::blas::dot(V_[i], V_[j + 1]);

		cusp::blas::axpy(V_[i], V_[j + 1], -H_(i,j));
	}

		H_(j+1,j) = cusp::blas::nrm2(V_[j + 1]);

		if(H_(j+1,j) < 1e-10) break;

		cusp::blas::scal(V_[j + 1], float(1) / H_(j+1,j));

     }
     toc("iteration");


     // scale V_ with beta, i.e. beta*V_, used later for computing simulation trace
     tic();
     for(int i = 0; i < maxiter; i++)
     {
        cusp::blas::scal(V_[i],beta);
     }
     toc("scaling matrix V with beta");
     

     // get matrix H (m x m dimension)
     tic(); 
     for(int rowH=0;rowH < maxiter; rowH++)
     for(int colH = 0; colH <maxiter; colH++)
		H(rowH,colH) = H_(rowH,colH);
     toc("get matrix H -- (m x m) dimension");


     // copying H matrix to np.ndarray
     tic();
    
     for (int i = 0; i < numIter; ++i )
	    for (int k = 0; k < numIter; ++k)
		    result_H[i*numIter + k] = H_(i,k);       
     toc("copying H to np.ndarray");
     
     if(j < maxiter)
     return j+1;
     else return maxiter;
}

int _arnoldi_initVectorPos(int basic_initVector_pos, double* result_H, int size, int numIter)
{   
    if (curMatrix == 0)
        error("loadMatrix must be called before running arnoldi algorithm");
    
    // create initial basic vector on device memory
    tic();

    cusp::array1d<FLOAT_TYPE,MEMORY_TYPE> deviceInitVec(size,0);

    deviceInitVec[basic_initVector_pos] = 1;
    toc("create initial basic vector on device memory based on its position, i.e. basic_initVector_pos");
    
    // system dimension 
    tic();
    int N = size;
    toc("get system dimension");

    // maximum number of Iteration of Arnoldi algorithm
    tic();
    int maxiter = std::min(N, numIter);
    toc("get maximum number of iteration of arnoldi algorithm");

    // create matrix H_ in device memory for iteration
    tic();	
    cusp::array2d<FLOAT_TYPE,MEMORY_TYPE> H_(maxiter + 1, maxiter, 0);
    toc("create matrix H_ in device memory for iteration");

    // returned matrix H after iteration -- Hm in the algorithm -- (m x m) matrix 
    tic();
    cusp::array2d<FLOAT_TYPE,MEMORY_TYPE> H(maxiter, maxiter); 
    toc("create returned matrix H after iteration -- Hm in the algorithm -- (m x m) matrix ");

    // create matrix V_ for iteration
    tic();
    V_.resize(maxiter+1);
    for (int i = 0; i < maxiter + 1; i++)
        V_[i].resize(N);
    toc("create matrix V_ for iteration");

    // copy initial vector into V_[0]
    tic(); 
    cusp::copy(deviceInitVec,V_[0]); 
    toc("copy initial vector into V_[0]"); 

    // iteration
    tic();
    int j;
    for(j = 0; j < maxiter; j++)
    {
	cusp::multiply(*curMatrix, V_[j], V_[j + 1]);
    
	for(int i = 0; i <= j; i++)
	{
		H_(i,j) = cusp::blas::dot(V_[i], V_[j + 1]);

		cusp::blas::axpy(V_[i], V_[j + 1], -H_(i,j));
	}

		H_(j+1,j) = cusp::blas::nrm2(V_[j + 1]);

		if(H_(j+1,j) < 1e-10) break;

		cusp::blas::scal(V_[j + 1], float(1) / H_(j+1,j));

     }
     toc("iteration time of Arnoldi algorithm");
         
     // get matrix H (m x m dimension)
     tic(); 
     for(int rowH=0;rowH < maxiter; rowH++)
	    for(int colH = 0; colH <maxiter; colH++)
		    H(rowH,colH) = H_(rowH,colH);
     toc("get matrix H -- (m x m) dimension");


     // copying H matrix to np.ndarray
     tic();
    
     for (int i = 0; i < numIter; ++i )
	    for (int k = 0; k < numIter; ++k)
		    result_H[i*numIter + k] = H_(i,k);       
     toc("copying H to np.ndarray");

     if(j < maxiter)
     return j+1;
     else return maxiter;
}


int _arnoldi_parallel(int size, int numIter,double* result_H)
{   
    if (curMatrix == 0)
        error("loadMatrix must be called before running arnoldi algorithm");
    
    // maximum number of Iteration of Arnoldi algorithm
    tic();
    int maxiter = std::min(size, numIter);
    toc("get maximum number of iteration of arnoldi algorithm");

    // create matrix V_all to contain all matrix V: V_all = [V0 V1 ...Vm]
    // V0 = [V0_1 ... V0_n] is (n x n) matrix containing all initial vectors of n-dimensions system
    // Vi = [Vi_1 ... Vi_n] is (n x n) matrix containing all i-th vectors in step i of Arnoldi algorithm
    
    tic();
    V_all.resize(maxiter+1);
    toc("create matrix V_all to contain all matrix Vm");

    // create matrix V_all_final to contain all matrix V; V_all_final = [Vm_0 Vm_2 ...Vm_(n-1)]
    // Vm_0 is the matrix (n x m) V (obtained from Arnoldi algorithm) that corresponds to the 0-th initial vector  
    // Vm_i is the (n x m) matrix V (obtained from Arnoldi algorithm) that corresponds to the i-th initial vector
    
    tic();
    V_all_final.resize(size);
    toc("create matrix V_all_final to contain all matrix Vm");    

    // create matrix H_all to contain all matrix H: H_all = [Hm_1 Hm_2 ...Hm_n]
    // Hm_1, Hm_2 , ... Hm_n are m x m matrices, Hm_i is conresponding to the initial vector i 
        
    tic();
    H_all.resize(size+1);
    toc("create matrix H_all to contain all matrix H");

     // create initial basic vector V_all[0] = n-dimension identity mat
    tic();
    cusp::array2d<FLOAT_TYPE,MEMORY_TYPE> identity_mat(size,size,0);
    cusp::array2d<FLOAT_TYPE,MEMORY_TYPE> zero_Vmat(size,size,0);
    cusp::array2d<FLOAT_TYPE, MEMORY_TYPE> Hmat_k(maxiter+1,maxiter,0);
    
   
    for (int i = 0; i < size; i++)
        for(int j = 0; j < size; j++)
            if (i == j) identity_mat(i,j) = 1;
    
    for (int i = 0; i< size; i++)
        cusp::copy(Hmat_k,H_all[i]); // initialize H_all[i] 

    for (int i = 1; i < maxiter+1; i++)
        cusp::copy(zero_Vmat,V_all[i]); // initalize V_all[i]

    cusp::copy(identity_mat,V_all[0]); // initialize V_all[0] by basic initial vectors
    
    toc("initialize V_all and H_all, create all initial basic vector on device memory V_all[0]");
    
    // Arnoldi parallel algorithm iteration

 
    cusp::array2d<FLOAT_TYPE,MEMORY_TYPE> Vj_plus1(size,size,0);
    cusp::array2d<FLOAT_TYPE,MEMORY_TYPE> Vi(size,size,0);
    cusp::array1d<FLOAT_TYPE,MEMORY_TYPE> Vj_plus1_col_k(size); 
    cusp::array1d<FLOAT_TYPE,MEMORY_TYPE> Vi_col_k(size);
    
    tic();
    int j;
    for (j = 0; j < maxiter; j++){

        cusp::multiply(*curMatrix,V_all[j],V_all[j+1]);
         
        cusp::copy(V_all[j+1],Vj_plus1);
  
        for(int k = 0; k < size; k++){
            // compute Hm-k 

            for(int l = 0; l < size; l++){
                Vj_plus1_col_k[l] = Vj_plus1(l,k); // Load column k of Vj_plus1
            }

            cusp::copy(H_all[k],Hmat_k); // Load k-th Hmat matrix         
                
            for(int i = 0; i <= j; i++){
                
                cusp::copy(V_all[i],Vi);

                for(int l = 0; l < size; l++){

                    Vi_col_k[l] = Vi(l,k); // Load column k of Vi
                    
                }
                

                Hmat_k(i,j) = cusp::blas::dot(Vi_col_k, Vj_plus1_col_k);
                
                cusp::blas::axpy(Vi_col_k, Vj_plus1_col_k, -Hmat_k(i,j));

            }
            
            Hmat_k(j+1,j) = cusp::blas::nrm2(Vj_plus1_col_k);

		    if(Hmat_k(j+1,j) < 1e-10) break;

		    cusp::blas::scal(Vj_plus1_col_k, float(1) / Hmat_k(j+1,j));
            
            for(int l = 0; l < size; l++){
                Vj_plus1(l,k) =  Vj_plus1_col_k[l]; // update  column k of Vj_plus1
            }

            cusp::copy(Hmat_k,H_all[k]); // update the k-th Hmatrix
            
        }

        cusp::copy(Vj_plus1,V_all[j+1]); // update column k of  V_all[j+1], i.e. corresponding to the k-th initial vector

    }
    
    toc("iteration time of Arnoldi algorithm");

     // copying H matrix to np.ndarray
     tic();
    
      // copying H matrix to np.ndarray
     tic();
     cusp::array2d<FLOAT_TYPE,MEMORY_TYPE> H(maxiter+1,maxiter,0);
     for (int k = 0; k< size; ++k){   
         cusp::copy(H_all[k],H);
         for (int i = 0; i < numIter; ++i){
             for(int l = 0; l < numIter; ++l)
                 result_H[i*numIter + l + k*numIter*numIter] = H(i,l);
         }
     }
          
     toc("copying H matrix to np.ndarray");

     int actual_numIter = 0; 

    // return actual number of iteration     
    if(j < maxiter)
    actual_numIter = j+1;
    else actual_numIter = maxiter;

    
     // save all matrix Vm into V_all_final
     tic();
     cusp::array2d<FLOAT_TYPE,MEMORY_TYPE> Vm(size,actual_numIter,0); 
    
     
     for (int k = 0; k < size; k++){

         for(int i = 0; i < actual_numIter; i++){

             cusp::copy(V_all[i],Vi);

             for (int l = 0; l < size; l++){

                 Vm(l,i) = Vi(l,k); // fill the column i- of Vm by the column k of V                 
             }    
         }
         cusp::copy(Vm, V_all_final[k]);

     }   
     
     toc("save all matrix Vm into V_all_final");
     

    return actual_numIter;
    
}


void _sim(double* matrix_Hf, double* sim_result, int size, int actual_numIter, int numStep)
{
    // compute the simulation result and copy the result back to the CPU (in the sim_result variable)  	  
    // copy matrix Hf to device memory
    numStepOfSim = numStep;
    systemSize   = size;
    tic();
    cusp::array2d<FLOAT_TYPE,MEMORY_TYPE> deviceMatrix_Hf(actual_numIter,numStep);
    for(int k=0; k< numStep ; k++)
       for(int i = 0; i < actual_numIter; i++)
          deviceMatrix_Hf(i,k) = matrix_Hf[i*numStep+k];
    toc("copying matrix Hf to device memory");

    // compute simulation result 
    tic();
    device_sim_result.resize(numStep);
    for (int i = 0; i < numStep; i++)
        device_sim_result[i].resize(size);        
    toc("create simulation result matrix");

    tic();
    for (int i=0; i< numStep; i++)
    {
        for(int k=0; k < actual_numIter; k++)
        {
	      cusp::blas::axpy(V_[k], device_sim_result[i], deviceMatrix_Hf(k,i));
        }

    }
    toc("compute simulation result");

    // copy simulation result to np.ndarray
    tic();
    for(int i = 0; i < numStep; i++)
       for(int k = 0; k < size; k++)
       {
		sim_result[i*numStep + k] = device_sim_result[i][k];		
		
       }
    toc("copy simulation result to np.ndarray");
           
}

void _sim2(double* matrix_Hf, int size, int actual_numIter, int numStep)
{
    numStepOfSim = numStep;
    systemSize   = size;
    // compute simulation result and save on the device memory. Do not return the simulation result back to CPU     	  
    // copy matrix Hf to device memory
    tic();
    cusp::array2d<FLOAT_TYPE,MEMORY_TYPE> deviceMatrix_Hf(actual_numIter,numStep);
    for(int k=0; k< numStep ; k++)
       for(int i = 0; i < actual_numIter; i++)
          deviceMatrix_Hf(i,k) = matrix_Hf[i*numStep+k];
    toc("copying matrix Hf to device memory");

    // compute simulation result 
    tic();
    device_sim_result.resize(numStep);
    for (int i = 0; i < numStep; i++)
        device_sim_result[i].resize(size);        
    toc("create simulation result matrix");

    tic();
    for (int i=0; i< numStep; i++)
    {
        for(int k=0; k < actual_numIter; k++)
        {
	      cusp::blas::axpy(V_[k], device_sim_result[i], deviceMatrix_Hf(k,i));
        }

    }
    toc("compute simulation result without copy the result back to CPU"); 
}


void _getKeySimResult(double* keySimResult)
{   // Get the simulation result in a particular dimension, where the dimension is specified by a sparse matrix
    // Steps for using this function:
    // Step1. Load the direction sparse matrix by calling _loadKeyDirMatrix() function
    // Step2. Run the arnoldi algorithm by calling arnoldi_initVector() or arnoldi_initVectorPos()
    // Step3. Compute the matrix Hf = exp(i*timeStep*Hm)
    // Step4. Call _sim2() to compute the simulation result. This function saves the result on device memory and doesnot copy the result to the CPU
    // Step5. Call this function to get the simulation result at this particular dimension

    tic();
    // check consistency and compute key simulation result
    if (numStepOfSim == 0 || systemSize == 0) // check if there is simulation result in device memory
        printf("\n There is no simulation result. Call _sim2() method first");
    else
    {   printf("\n Number of simulation step = %d",numStepOfSim);
        printf("\n Number of Rows of key direction matrix = %d", keyDirMatrix_w);
        if (keyDirMatrix_h != systemSize) // check consistency between the key direction matrix and system dimension
        {
             printf("\n The number of column of key direction matrix is inconsistent with the system dimension");
             toc("check consistency");
        }   
        else
        {   // create key simulation result in device memory
            tic();
            std::vector< cusp::array1d<FLOAT_TYPE,MEMORY_TYPE> > device_keySimResult(numStepOfSim);
            for (int i = 0; i < numStepOfSim; i++)
                device_keySimResult[i].resize(keyDirMatrix_w);
            toc("\n Create keySimResult in device memory");
            
            // compute key simulation result
            tic();
            
            for(int i = 0; i <numStepOfSim; i++)
            {
                cusp::multiply(*keyDirMatrix, device_sim_result[i],device_keySimResult[i]);
            }
            toc("\n Compute key simulation result");

            // copy key direction simulation result to np.array
            tic();
            for(int i = 0; i < numStepOfSim; i++)
                for(int k = 0; k < keyDirMatrix_w; k++)
                   {
		                keySimResult[i*numStepOfSim + k] = device_keySimResult[i][k];		
                   }
            toc("\n Copy key simulation result to np.array");
               
        }
        
    } 
    
}

void _getKeySimResult_parallel(int size, int H_numRows, double* expHt_tuples)
{
    // get Simulation result in specific direction defined by keyDirMatrix
    // SimResult = V*exp(H*t)*e1, (V,H) are matrices obtained from Arnoldi algorithm
    // KeySimResult = keyDirMatrix*SimResult

    // Check consitency 
    if (keyDirMatrix_h != size) // check consistency between the key direction matrix and system dimension
        {
             printf("\n The number of column of key direction matrix is inconsistent with the system dimension");
             toc("check consistency");
        }
    else{
        tic();
        expHt_all.resize(size);
        cusp::array2d<FLOAT_TYPE,MEMORY_TYPE> device_expHt(H_numRows,H_numRows,0);

        for (int i = 0; i < size; i++){           
            for(int k=0; k< H_numRows ; k++)
               for(int l = 0; l < H_numRows; l++)
                  device_expHt(k,l) = expHt_tuples[k*H_numRows+l+i*H_numRows*H_numRows];

            cusp::copy(device_expHt,expHt_all[i]);

            printf("The %d-th exp(Ht) matrix is: \n",i);
            cusp::print(expHt_all[i]);
            
        }

        toc("copying exp(H*t) into device memory"); 

      }
    
    
}

int _hasGpu()
{
    int rv = 1;
    
    try
    {
        cusp::array1d<FLOAT_TYPE, cusp::host_memory> hostVec(10);
    
        for (int i = 0; i < 10; ++i)
            hostVec[i] = 0;

        cusp::array1d<FLOAT_TYPE,MEMORY_TYPE> deviceVec(hostVec);
    }
    catch(std::exception &e)
    {
        printf("hasGpu() Failed: %s\n", e.what());
        rv = 0;
    }
    
    return rv;
}

extern "C"
{
int hasGpu()
{
    return _hasGpu();
}

void choose_GPU_or_CPU(char* msg)
{
    _choose_GPU_or_CPU(msg);
}

void loadMatrix(int w, int h, int* nonZeroRows, int* nonZeroCols, double* nonZeroEntries, int nonZeroCount)
{
    _loadMatrix(w, h, nonZeroRows, nonZeroCols, nonZeroEntries, nonZeroCount);
}


void loadKeyDirMatrix(int w, int h, int* nonZeroRows, int* nonZeroCols, double* nonZeroEntries, int nonZeroCount)
{
    _loadKeyDirMatrix(w, h, nonZeroRows, nonZeroCols, nonZeroEntries, nonZeroCount);
}
    
int arnoldi_initVector(double* init_vector, double* result_H, int size, int numIter)
{
   return _arnoldi_initVector(init_vector, result_H, size, numIter);
   
}

int arnoldi_initVectorPos(int basic_initVector_pos, double* result_H, int size, int numIter)
{
   return _arnoldi_initVectorPos(basic_initVector_pos, result_H, size, numIter);
}

    int arnoldi_parallel(int size, int numIter, double* result_H)
{
    return _arnoldi_parallel(size, numIter,result_H);
}

void sim(double* matrix_Hf, double* sim_result, int size, int actual_numIter, int numStep)\
{
    _sim(matrix_Hf, sim_result,  size, actual_numIter, numStep);
}
    
void sim2(double* matrix_Hf, int size, int actual_numIter, int numStep)\
{
    _sim2(matrix_Hf, size, actual_numIter, numStep);

}

void getKeySimResult(double* keySimResult)
{
    _getKeySimResult(keySimResult);
}

    
void getKeySimResult_parallel(int size, int numIter, double* expHt_tuples)
{
    _getKeySimResult_parallel(size,numIter,expHt_tuples);   
}

}
